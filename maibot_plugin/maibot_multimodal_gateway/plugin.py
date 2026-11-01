"""MaiBot Host/Runner bridge; subscription authentication stays in Gateway."""
import asyncio
from pathlib import Path
import tempfile
import time
from typing import Literal

from maibot_sdk import Command, Field, LLMProvider, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from . import provider as provider_wire
from .client import GatewayClient, GatewayError, Settings, artifact, provider_messages, response_text, route, text_model

TIMEOUT_MS = 660000
HELP = ('本機多模態 Gateway：\n/mm status\n/mm chat grok|gpt|gemini 文字\n'
        '/mm image grok|gpt|gemini 圖片描述\n影片使用 gateway_video 工具，需另開啟插件影片功能與 Host 檔案服務。')


class PluginSection(PluginConfigBase):
    enabled: bool = Field(default=False, description='啟用本機測試插件')
    config_version: str = Field(default='0.1.0', description='設定版本')


class GatewaySection(PluginConfigBase):
    base_url: str = Field(default='http://127.0.0.1:8790', description='同機 Gateway 原點，不含 /v1')
    key_file: str = Field(default='', description='Gateway key 的絕對檔案路徑，需同使用者持有且權限 0600；不是服務商 key')
    timeout_seconds: float = Field(default=630, ge=10, le=900, description='單次 HTTP timeout；媒體建議 630 秒')


class AccessSection(PluginConfigBase):
    allowed_stream_ids: list[str] = Field(default_factory=list, max_length=64, description='僅允許的 Mai Chat 測試流 ID；用 /mm status 查看，空清單拒絕生成')
    cooldown_seconds: float = Field(default=5, ge=0, le=3600, description='同一測試流生成請求的最短間隔')


class FeatureSection(PluginConfigBase):
    text_enabled: bool = Field(default=True, description='開啟明確文字命令')
    image_enabled: bool = Field(default=True, description='開啟明確生圖命令')
    tools_enabled: bool = Field(default=False, description='允許 MaiBot 模型選用圖片／影片工具；會使用訂閱額度')
    video_enabled: bool = Field(default=False, description='允許 Grok 影片工具；須開啟 Host 檔案服務')
    provider_tool_calls_enabled: bool = Field(default=False, description='允許 grok JSON 工具呼叫橋接；工具由 MaiBot 執行，需保留 Host 權限控制')
    provider_vision_enabled: bool = Field(default=False, description='允許 grok 接收使用者 base64 圖片')
    llm_provider_enabled: bool = Field(default=False, description='開啟模型 Provider；進階多模態使用 grok 路由')


class GatewayPluginConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    gateway: GatewaySection = Field(default_factory=GatewaySection)
    access: AccessSection = Field(default_factory=AccessSection)
    features: FeatureSection = Field(default_factory=FeatureSection)


class MultimodalGatewayPlugin(MaiBotPlugin):
    config_model = GatewayPluginConfig

    def __init__(self):
        super().__init__()
        self._pending = None
        self._closing = False
        self._last_requests = {}

    async def on_load(self):
        self._closing = False
        self.ctx.logger.info('Local multimodal Gateway plugin loaded; no requests started.')

    async def on_unload(self):
        self._closing = True
        # An HTTP disconnect cannot cancel provider generation. Do not retry or
        # release the local request slot while its worker is still running.

    async def on_config_update(self, scope, config_data, version):
        if scope == 'self':
            self.set_plugin_config(config_data)

    def _authorize(self, stream_id, platform, *, tool=False):
        if self._closing or not self.config.plugin.enabled:
            raise GatewayError('plugin_not_enabled')
        if platform != 'internal' or not stream_id or stream_id not in self.config.access.allowed_stream_ids:
            raise GatewayError('test_stream_not_authorized')
        if tool and not self.config.features.tools_enabled:
            raise GatewayError('model_tools_not_enabled')

    async def _request(self, operation, body=None, *, stream_id=None):
        if self._pending is not None and not self._pending.done():
            raise GatewayError('plugin_busy')
        now = time.monotonic()
        if stream_id is not None:
            previous = self._last_requests.get(stream_id)
            if previous is not None and now - previous < self.config.access.cooldown_seconds:
                raise GatewayError('stream_cooldown')
        client = GatewayClient(Settings(self.config.gateway.base_url, self.config.gateway.key_file,
                                        self.config.gateway.timeout_seconds))
        if stream_id is not None:
            self._last_requests[stream_id] = now
        task = asyncio.create_task(asyncio.to_thread(client.request, operation, body))
        self._pending = task
        def finished(done):
            if not done.cancelled():
                done.exception()  # Consume a worker error even if its caller was cancelled.
            if self._pending is done:
                self._pending = None
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _send_text(self, text, stream_id):
        if self._closing:
            raise GatewayError('plugin_unloading')
        try:
            sent = await self.ctx.send.text(text, stream_id, return_details=True)
            if not isinstance(sent, dict) or sent.get('sent') is not True:
                raise GatewayError('message_delivery_not_confirmed')
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('message_delivery_failed') from None

    async def _image(self, provider, prompt, stream_id):
        if not self.config.features.image_enabled:
            raise GatewayError('image_feature_disabled')
        result = await self._request('image', {'model': route(provider), 'prompt': prompt, 'n': 1, 'size': 'auto'}, stream_id=stream_id)
        image = artifact(result, 'image')
        if self._closing:
            raise GatewayError('plugin_unloading')
        try:
            sent = await self.ctx.send.image(image.encoded, stream_id, return_details=True)
            if not isinstance(sent, dict) or sent.get('sent') is not True:
                raise GatewayError('image_generated_delivery_not_confirmed')
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('image_generated_delivery_failed_do_not_regenerate') from None
        return {'success': True, 'content': '圖片已傳送。', 'media_type': image.media_type, 'sha256': image.sha256}

    @Command('mm', description='本機 Gateway 狀態、文字與生圖', pattern=r'^/mm(?:\s+(?P<arguments>[\s\S]*))?$', timeout_ms=TIMEOUT_MS)
    async def command(self, **kwargs):
        stream_id, platform = kwargs.get('stream_id', ''), kwargs.get('platform', '')
        # Host supplies command context. Never send anything to a QQ stream.
        if platform != 'internal' or not stream_id:
            return False, None, 0
        groups = kwargs.get('matched_groups') or {}
        arguments = groups.get('arguments')
        if arguments is None:
            text = kwargs.get('text', '')
            arguments = text[3:].strip() if isinstance(text, str) and (text == '/mm' or text.startswith('/mm ')) else ''
        parts = arguments.strip().split(None, 2)
        try:
            if not parts:
                await self._send_text(HELP, stream_id)
            elif parts == ['status']:
                # Read-only setup discovery works before enabling generation.
                try:
                    result = await self._request('status')
                    state = '可連線' if result.get('status') == 'ok' else '回應異常'
                except GatewayError as error:
                    state = error.code
                await self._send_text(f'Gateway：{state}\n目前測試流 ID：{stream_id}\n插件啟用：{self.config.plugin.enabled}', stream_id)
            elif len(parts) == 3 and parts[0] in ('chat', 'image'):
                self._authorize(stream_id, platform)
                operation, provider, prompt = parts
                if not prompt.strip() or len(prompt) > 16000:
                    raise GatewayError('invalid_prompt')
                if operation == 'image':
                    await self._image(provider, prompt, stream_id)
                else:
                    if not self.config.features.text_enabled:
                        raise GatewayError('text_feature_disabled')
                    result = await self._request('chat', {'model': route(provider), 'messages': [
                        {'role': 'user', 'content': prompt}], 'stream': False}, stream_id=stream_id)
                    await self._send_text(response_text(result), stream_id)
            else:
                await self._send_text(HELP, stream_id)
            return True, None, 2
        except GatewayError as error:
            # Fixed local error codes only. Provider bodies/key paths stay local.
            try:
                await self._send_text(f'Gateway 請求未完成：{error}。不會自動重試；請檢查本機 Gateway。', stream_id)
            except GatewayError:
                pass
            return False, None, 2

    @Tool('gateway_image', brief_description='用本機訂閱 Gateway 生成一張圖片並回傳目前測試聊天',
          detailed_description='僅在使用者明確要求生圖時呼叫一次。失敗或傳送未確認時不要自動重試。',
          parameters=[ToolParameterInfo(name='provider', param_type=ToolParamType.STRING,
                          enum_values=['grok', 'gpt', 'gemini'], description='指定訂閱提供者', required=True),
                      ToolParameterInfo(name='prompt', param_type=ToolParamType.STRING,
                          description='使用者的圖片描述', required=True)],
          platforms='internal', timeout_ms=TIMEOUT_MS)
    async def image_tool(self, provider: Literal['grok', 'gpt', 'gemini'], prompt: str, **kwargs):
        try:
            self._authorize(kwargs.get('stream_id', ''), kwargs.get('platform', ''), tool=True)
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
                raise GatewayError('invalid_prompt')
            return await self._image(provider, prompt, kwargs['stream_id'])
        except GatewayError as error:
            return {'success': False, 'content': str(error) + '；不要自動重試。'}

    @Tool('gateway_video', brief_description='透過本機 Grok 訂閱生成六秒影片並傳到目前測試聊天',
          detailed_description='只支援 Grok。需 Host 檔案服務；僅在使用者明確要求時呼叫一次，失敗不要自動重試。',
          parameters=[ToolParameterInfo(name='prompt', param_type=ToolParamType.STRING,
                          description='使用者的影片描述', required=True)],
          platforms='internal', timeout_ms=TIMEOUT_MS)
    async def video_tool(self, prompt: str, **kwargs):
        try:
            self._authorize(kwargs.get('stream_id', ''), kwargs.get('platform', ''), tool=True)
            if not self.config.features.video_enabled:
                raise GatewayError('video_feature_disabled')
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
                raise GatewayError('invalid_prompt')
            # Probe the actual tool-scoped file capability BEFORE spending quota.
            # No upload/registration is performed by this read-only availability check.
            try:
                available = await self.ctx.files.list()
                if not isinstance(available, list):
                    raise GatewayError('video_requires_host_file_service')
            except Exception:
                raise GatewayError('video_requires_host_file_service') from None
            result = await self._request('video', {'model': 'grok/default', 'prompt': prompt, 'duration': 6}, stream_id=kwargs['stream_id'])
            video = artifact(result, 'video')
            if self._closing:
                raise GatewayError('plugin_unloading')
            runtime = Path(self.ctx.paths.runtime_dir)
            if runtime.is_symlink():
                raise GatewayError('invalid_plugin_runtime_directory')
            runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(prefix='video-', dir=runtime) as folder:
                    path = Path(folder) / 'generated.mp4'
                    path.write_bytes(video.data)
                    path.chmod(0o600)
                    uploaded = await self.ctx.files.upload(path, name='grok-video.mp4', mime_type='video/mp4')
                    sent = await self.ctx.files.send(uploaded['file_ref'])
                if sent.get('status') != 'sent':
                    raise GatewayError('video_uploaded_delivery_not_confirmed_do_not_regenerate')
            except GatewayError:
                raise
            except Exception:
                raise GatewayError('video_generated_file_delivery_failed_do_not_regenerate') from None
            return {'success': True, 'content': '影片已傳送。', 'media_type': video.media_type, 'sha256': video.sha256}
        except GatewayError as error:
            return {'success': False, 'content': str(error) + '；不要自動重試。'}

    @LLMProvider('ayakanya.multimodal_gateway', name='Local Subscription Gateway', version='0.2.0')
    async def llm_provider(self, operation, request):
        if self._closing or not self.config.plugin.enabled or not self.config.features.llm_provider_enabled:
            raise GatewayError('text_provider_not_enabled')
        model = text_model(request.get('model_info', {}).get('model_identifier', ''))
        if operation == 'audio_transcription':
            raise GatewayError('supergrok_subscription_audio_file_interface_unavailable')
        if operation != 'response':
            raise GatewayError('unsupported_provider_operation')
        if model.startswith('grok/') and (self.config.features.provider_tool_calls_enabled or self.config.features.provider_vision_enabled):
            body = provider_wire.request_body(request, model, self.config.features)
            result = await self._request('chat', body)
            return provider_wire.output(result, body['tools'], modern='context_items' in request)
        messages = provider_messages(request)
        result = await self._request('chat', {'model': model, 'messages': messages, 'stream': False})
        return provider_wire.output(result, [], modern='context_items' in request)


def create_plugin():
    return MultimodalGatewayPlugin()
