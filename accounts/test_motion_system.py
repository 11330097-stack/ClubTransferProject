from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class MotionSystemContractTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.css = (Path(settings.BASE_DIR) / 'static/css/design-system.css').read_text(
            encoding='utf-8',
        )
        cls.workflow_js = (
            Path(settings.BASE_DIR) / 'static/js/workflow-forms.js'
        ).read_text(encoding='utf-8')

    def test_shared_motion_tokens_drive_component_interactions(self):
        self.assertIn('--motion-duration-fast: 140ms;', self.css)
        self.assertIn('--motion-duration-base: 180ms;', self.css)
        self.assertIn('--motion-duration-slow: 240ms;', self.css)
        self.assertIn('--motion-ease-out:', self.css)

    def test_reduced_motion_removes_nonessential_animation(self):
        reduced_motion = self.css.split('@media (prefers-reduced-motion: reduce)', 1)[1]

        self.assertIn('transition: none !important;', reduced_motion)
        self.assertIn('animation: none !important;', reduced_motion)
        self.assertIn('.btn.is-processing::before', reduced_motion)

    def test_only_the_triggered_submit_button_changes_label_and_keeps_width(self):
        self.assertIn('const activeButton = event.submitter', self.workflow_js)
        self.assertIn('button === activeButton', self.workflow_js)
        self.assertIn('button.getBoundingClientRect().width', self.workflow_js)
