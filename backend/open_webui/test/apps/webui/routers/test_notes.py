import copy

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_user


class TestNotes(AbstractPostgresTest):
    BASE_PATH = "/api/v1/notes"

    @classmethod
    def setup_class(cls):
        super().setup_class()
        from main import app

        cls.app = app

    def setup_method(self):
        super().setup_method()

        from open_webui.models.notes import NoteForm, Notes
        from open_webui.models.users import Users

        self.notes = Notes
        self.NoteForm = NoteForm
        self.users = Users

        self.owner_id = "user-1"
        self.shared_user_id = "user-2"
        self.viewer_id = "user-3"

        self.users.insert_new_user(
            self.owner_id,
            "Owner",
            "owner@example.com",
            role="user",
        )
        self.users.insert_new_user(
            self.shared_user_id,
            "Collaborator",
            "collaborator@example.com",
            role="user",
        )
        self.users.insert_new_user(
            self.viewer_id,
            "Viewer",
            "viewer@example.com",
            role="user",
        )

        self.existing_note = self.notes.insert_new_note(
            self.NoteForm(
                title="Existing note",
                data={
                    "content": {
                        "html": "<p>Hello</p>",
                        "md": "Hello",
                        "json": None,
                    }
                },
                meta=None,
                access_control={},
            ),
            self.owner_id,
        )

        self._permissions_backup = copy.deepcopy(
            self.app.state.config.USER_PERMISSIONS
        )
        self._notes_enabled_backup = self.app.state.config.ENABLE_NOTES
        self.app.state.config.ENABLE_NOTES = True

    def teardown_method(self):
        self.app.state.config.USER_PERMISSIONS = self._permissions_backup
        self.app.state.config.ENABLE_NOTES = self._notes_enabled_backup
        super().teardown_method()

    def test_create_note_success(self):
        body = {
            "title": "Meeting notes",
            "data": {
                "content": {
                    "html": "<p>Agenda</p>",
                    "md": "Agenda",
                    "json": None,
                }
            },
            "meta": None,
            "access_control": {},
        }

        with mock_user(self.app, id=self.owner_id, role="user"):
            response = self.fast_api_client.post(
                self.create_url("/create"),
                json=body,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == body["title"]
        assert data["user_id"] == self.owner_id
        assert data["data"]["content"]["md"] == "Agenda"

    def test_create_note_requires_permission(self):
        permissions = copy.deepcopy(self._permissions_backup)
        permissions.setdefault("features", {})["notes"] = False
        self.app.state.config.USER_PERMISSIONS = permissions

        body = {
            "title": "Blocked note",
            "data": {
                "content": {
                    "html": "<p>Blocked</p>",
                    "md": "Blocked",
                    "json": None,
                }
            },
            "meta": None,
            "access_control": {},
        }

        with mock_user(self.app, id=self.owner_id, role="user"):
            response = self.fast_api_client.post(
                self.create_url("/create"),
                json=body,
            )

        assert response.status_code == 401

    def test_get_notes_includes_shared_write_access(self):
        shared_note = self.notes.insert_new_note(
            self.NoteForm(
                title="Shared note",
                data={
                    "content": {
                        "html": "<p>Shared</p>",
                        "md": "Shared",
                        "json": None,
                    }
                },
                meta=None,
                access_control={
                    "write": {"user_ids": [self.shared_user_id], "group_ids": []}
                },
            ),
            self.owner_id,
        )

        with mock_user(self.app, id=self.shared_user_id, role="user"):
            response = self.fast_api_client.get(self.create_url("/"))

        assert response.status_code == 200
        note_ids = {note["id"] for note in response.json()}
        assert shared_note.id in note_ids
        assert self.existing_note.id not in note_ids

    def test_get_note_by_id_enforces_access_control(self):
        restricted_note = self.notes.insert_new_note(
            self.NoteForm(
                title="Private",
                data={
                    "content": {
                        "html": "<p>Private</p>",
                        "md": "Private",
                        "json": None,
                    }
                },
                meta=None,
                access_control={},
            ),
            self.owner_id,
        )

        with mock_user(self.app, id=self.viewer_id, role="user"):
            response = self.fast_api_client.get(
                self.create_url(f"/{restricted_note.id}")
            )

        assert response.status_code == 403

