import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from gateway import app, media


PNG = b'\x89PNG\r\n\x1a\ntrusted-image'


class ArtifactPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.real = self.base/'private-var/work'
        self.real.mkdir(parents=True)
        (self.base/'var').symlink_to(self.base/'private-var', target_is_directory=True)
        self.alias = self.base/'var/work'
        (self.real/'image.png').write_bytes(PNG)
    def tearDown(self):
        self.temp.cleanup()
    def test_macos_style_root_ancestor_alias_in_both_path_spellings(self):
        for root in (self.real, self.alias):
            for image in (self.real/'image.png', self.alias/'image.png'):
                with self.subTest(root=root, image=image):
                    result = media.read_artifact(image, root, 'image')
                    self.assertEqual(base64.b64decode(result['b64_json']), PNG)
    def test_file_and_directory_links_inside_artifact_root_are_denied(self):
        outside = self.base/'outside';outside.mkdir()
        (outside/'image.png').write_bytes(PNG)
        (self.real/'internal-link.png').symlink_to(self.real/'image.png')
        (self.real/'external-link.png').symlink_to(outside/'image.png')
        (self.real/'directory-link').symlink_to(outside, target_is_directory=True)
        for image in (self.alias/'internal-link.png',self.real/'external-link.png',self.alias/'directory-link/image.png'):
            with self.subTest(image=image), self.assertRaises(app.Failure) as caught:
                media.read_artifact(image, self.alias, 'image')
            self.assertEqual(caught.exception.code, 'unsafe_media_path')
    def test_outside_traversal_and_linked_boundary_are_denied(self):
        (self.base/'linked-root').symlink_to(self.real, target_is_directory=True)
        for image,root in ((self.base/'elsewhere.png',self.alias),
                (self.alias/'other/../image.png',self.alias),
                (self.base/'linked-root/image.png',self.base/'linked-root')):
            with self.subTest(image=image), self.assertRaises(app.Failure) as caught:
                media.read_artifact(image, root, 'image')
            self.assertEqual(caught.exception.code, 'unsafe_media_path')
    def test_pinned_directory_does_not_follow_replacement_link(self):
        images=self.real/'images';images.mkdir()
        (images/'image.png').write_bytes(PNG)
        outside=self.base/'outside';outside.mkdir()
        (outside/'image.png').write_bytes(b'\x89PNG\r\n\x1a\nexternal-image')
        native_open=media.os.open
        def swap(path,flags,**kwargs):
            if path == 'image.png':
                images.rename(self.real/'original-images')
                images.symlink_to(outside, target_is_directory=True)
            return native_open(path,flags,**kwargs)
        with patch.object(media.os,'open',side_effect=swap):
            result=media.read_artifact(self.alias/'images/image.png',self.alias,'image')
        self.assertEqual(base64.b64decode(result['b64_json']), PNG)


if __name__ == '__main__':
    unittest.main()
