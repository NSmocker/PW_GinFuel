"""Worker composition root for the clean session implementation."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from clean_arch.application.quest_controller import QuestController  # noqa: E402
from clean_arch.application.session_client import SessionClient  # noqa: E402
from clean_arch.domain.models import LogLine, SessionMode  # noqa: E402
from clean_arch.infrastructure.wire import ProtocolError  # noqa: E402
from config import config_int, load_config, resolve_server_from_userdata  # noqa: E402
from credentials import load_credentials  # noqa: E402
from error_messages import find_error_file, load_error_messages  # noqa: E402


class CleanSessionWorker:
    def run(self, settings, emit: Callable[[LogLine], None]) -> int:
        config = load_config(settings.config_path)
        username, password = load_credentials(settings.credentials_path)
        host = config.get("host")
        port = config_int(config, "port")
        if not host or port is None:
            host, port = resolve_server_from_userdata(config["userdata_folder"])
        game_client_root = config.get("game_client_root")
        if not game_client_root:
            candidate = os.path.dirname(os.path.abspath(settings.config_path))
            if os.path.isfile(os.path.join(candidate, "ingame.stf")):
                game_client_root = candidate
        client = SessionClient(host, port, emit,
                               source_root=config.get("client_source_root"),
                               game_client_root=game_client_root,
                               elements_root=config.get("elements_root"),
                               tasks_root=config.get("tasks_root"))
        client.log(f"Protocol catalog: {len(client.catalog.protocols)} protocols, "
               f"{len(client.catalog.c2s_commands)} C2S commands, "
               f"{len(client.catalog.s2c_commands)} S2C commands, "
               f"{len(client.catalog.errors)} error codes")
        client.error_messages = load_error_messages(find_error_file(config))
        client.start_control_channel()
        try:
            client.connect()
            client.login(username, password)
            roles = client.get_roles()
            if not roles:
                client.log("The account has no characters", ok=False)
                return 1
            for index, role in enumerate(roles, 1):
                client.log(f"Character {index}: {role.name} "
                           f"(id={role.roleid}, level={role.level})")
            role_id = config_int(config, "role_id")
            role_index = config_int(config, "role_index") or 1
            role = next((item for item in roles if item.roleid == role_id), None) if role_id else None
            role = role or (roles[role_index - 1] if 1 <= role_index <= len(roles) else None)
            if role is None:
                client.log("Could not pick a character", ok=False)
                return 1
            if settings.mode is SessionMode.LOGIN_ONLY:
                client.run_login_only()
            else:
                client.enter_world(role)
                quest = None
                return_id = config_int(config, "quest_return_id") or 0
                if return_id:
                    quest = QuestController(
                        client, return_id,
                        config_int(config, "quest_accept_id") or 0,
                        config_int(config, "quest_pending_id") or 17064,
                        config_int(config, "quest_cycles") or 0,
                        config_int(config, "quest_retry_minutes") or 5,
                        float(config.get("quest_command_delay", "1.5")),
                        config_int(config, "npc_id") or 0,
                        config_int(config, "npc_template_id") or 0)
                client.run_world(quest)
        except (ConnectionError, OSError, ValueError, ProtocolError) as error:
            client.log(f"Client error: {error}", ok=False)
            return 1
        finally:
            client.close()
        return 0
