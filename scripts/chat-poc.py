"""Explicit Grok subscription vision/tool PoC; no MaiBot/QQ connection."""
import argparse
import base64
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'maibot_plugin'))
from maibot_multimodal_gateway.client import GatewayClient, GatewayError, Settings
from maibot_multimodal_gateway.provider import encoded_media


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--tool-demo', action='store_true', help='Allow only a local echo tool; at most two model calls')
    parser.add_argument('--model', default='grok/default')
    args=parser.parse_args()
    if not args.model.startswith('grok/'):
        parser.error('This PoC uses the Grok subscription route only.')
    try:
        client=GatewayClient(Settings('http://127.0.0.1:8790',str(ROOT/'.state/gateway.key')))
        content=args.prompt
        if args.image:
            fd=os.open(args.image,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.fdopen(fd,'rb') as source:
                info=os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size>4*1024*1024:
                    raise GatewayError('image_requires_regular_file_up_to_4_mib')
                data=source.read(4*1024*1024+1)
            _,url=encoded_media(base64.b64encode(data).decode())
            content=[{'type':'text','text':args.prompt},{'type':'image_url','image_url':{'url':url}}]
        body={'model':args.model,'messages':[{'role':'user','content':content}],'stream':False,'tools':[]}
        if args.tool_demo:
            body['tools']=[{'type':'function','function':{'name':'gateway_echo','description':'Echo text locally; no external actions.',
                'parameters':{'type':'object','properties':{'text':{'type':'string','maxLength':4000}},
                              'required':['text'],'additionalProperties':False}}}]
        message=client.request('chat',body)['choices'][0]['message']
        calls=message.get('tool_calls',[])
        if calls:
            if not args.tool_demo or len(calls)!=1: raise GatewayError('unexpected_demo_tool')
            call=calls[0];params=json.loads(call['function']['arguments'])
            if (call.get('type')!='function' or call['function']['name']!='gateway_echo' or
                not isinstance(params,dict) or set(params)!={'text'} or not isinstance(params['text'],str) or len(params['text'])>4000):
                raise GatewayError('invalid_demo_tool_arguments')
            body['messages'] += [message,{'role':'tool','tool_call_id':call['id'],'content':'Echo: '+params['text']}]
            print('Validated local echo executed once; requesting the final answer.')
            message=client.request('chat',body)['choices'][0]['message']
            if message.get('tool_calls'): raise GatewayError('demo_stopped_after_one_tool_no_retry')
        elif args.tool_demo:
            print('Model returned text without selecting the demo tool.')
        text=message.get('content')
        if not isinstance(text,str) or not text.strip(): raise GatewayError('missing_final_text')
        print(text)
    except (GatewayError,OSError,ValueError,KeyError,IndexError,TypeError) as error:
        print(str(error) if isinstance(error,GatewayError) else 'PoC failed; check the local input file and Gateway.',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
