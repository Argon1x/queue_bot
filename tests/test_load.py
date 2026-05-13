import sys
sys.path.insert(0, "..")

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from telegram.error import BadRequest


class TestErrorHandlerLoad:
    def test_bad_request_message_not_modified_is_silent(self):
        from bot import error_handler
        update = MagicMock()
        context = MagicMock()
        context.error = BadRequest("Message is not modified")
        update.effective_chat = None
        result = asyncio.run(error_handler(update, context))
        assert result is None

    def test_bad_request_other_still_logged(self):
        from bot import error_handler
        update = MagicMock()
        context = MagicMock()
        context.error = BadRequest("Something else")
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        context.bot.send_message = AsyncMock()
        asyncio.run(error_handler(update, context))
        context.bot.send_message.assert_awaited_once()

    def test_other_errors_still_handled(self):
        from bot import error_handler
        update = MagicMock()
        context = MagicMock()
        context.error = ValueError("test error")
        update.effective_chat = MagicMock()
        update.effective_chat.id = 1
        context.bot.send_message = AsyncMock()
        asyncio.run(error_handler(update, context))
        context.bot.send_message.assert_awaited_once()

    def test_error_without_chat_no_crash(self):
        from bot import error_handler
        update = MagicMock()
        context = MagicMock()
        context.error = BadRequest("Message is not modified")
        update.effective_chat = None
        result = asyncio.run(error_handler(update, context))
        assert result is None


class TestMoveToFrontQueryPattern:
    def test_get_active_members_uses_sort_order(self):
        with open("data.py") as f:
            content = f.read()
        assert "ORDER BY sort_order, id" in content

    def test_join_queue_inserts_sort_order(self):
        with open("data.py") as f:
            content = f.read()
        assert "MAX(sort_order)" in content
        assert "sort_order" in content.split("INSERT INTO queue_members")[1]

    def test_move_to_front_defined(self):
        import data
        assert hasattr(data, "move_to_front")

    def test_init_db_has_alter_table(self):
        with open("data.py") as f:
            content = f.read()
        assert "ALTER TABLE queue_members ADD COLUMN IF NOT EXISTS sort_order" in content


class TestConversationStates:
    def test_link_command_returns_waiting_link_name(self):
        import bot
        update = MagicMock()
        update.effective_user.id = 123
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = []
        context.user_data = {}
        with patch("bot.get_user_profile", AsyncMock(return_value=None)):
            result = asyncio.run(bot.link_command(update, context))
            assert result == bot.WAITING_LINK_NAME

    def test_link_command_with_args_returns_end(self):
        import bot
        from telegram.ext import ConversationHandler
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.username = "test"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["TestName"]
        context.user_data = {}
        with patch("bot.set_user_profile", AsyncMock()):
            result = asyncio.run(bot.link_command(update, context))
            assert result == ConversationHandler.END

    def test_link_command_with_args_too_long_returns_end(self):
        import bot
        from telegram.ext import ConversationHandler
        update = MagicMock()
        update.effective_user.id = 123
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.args = ["A" * 60]
        context.user_data = {}
        result = asyncio.run(bot.link_command(update, context))
        assert result == ConversationHandler.END

    def test_text_input_link_name_valid(self):
        import bot
        from telegram.ext import ConversationHandler
        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.username = "test"
        update.message.text = "Иван"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"action": "link_name"}
        context.bot.send_message = AsyncMock()
        with patch("bot.set_user_profile", AsyncMock()):
            result = asyncio.run(bot.text_input(update, context))
            assert result == ConversationHandler.END

    def test_text_input_link_name_empty_stays(self):
        import bot
        update = MagicMock()
        update.effective_user.id = 123
        update.message.text = "   "
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"action": "link_name"}
        result = asyncio.run(bot.text_input(update, context))
        assert result == bot.WAITING_LINK_NAME

    def test_text_input_link_name_too_long_stays(self):
        import bot
        update = MagicMock()
        update.effective_user.id = 123
        update.message.text = "A" * 60
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"action": "link_name"}
        result = asyncio.run(bot.text_input(update, context))
        assert result == bot.WAITING_LINK_NAME


class TestMoveToFrontLogic:
    def test_move_to_front_first_member_returns(self):
        import data
        with patch("data.fetchrow", AsyncMock(return_value={
            "id": 1, "queue_id": 1, "display_name": "Test", "status": "active"
        })):
            with patch("data.fetchrow", AsyncMock(side_effect=[
                {"id": 1, "queue_id": 1, "display_name": "Test", "status": "active"},
                {"sort_order": 1},
            ])):
                with patch("data.execute", AsyncMock()):
                    with patch("data._log_event", AsyncMock()):
                        result = asyncio.run(data.move_to_front(1, 1, 0))
                        assert result is not None

    def test_get_active_members_order(self):
        import data
        with patch("data.fetch") as mock_fetch:
            mock_fetch.return_value = [
                {"id": 1, "telegram_user_id": 1, "username": "", "display_name": "A"},
                {"id": 2, "telegram_user_id": 2, "username": "", "display_name": "B"},
            ]
            result = asyncio.run(data.get_active_members(1))
            assert len(result) == 2
            sql = mock_fetch.call_args[0][0]
            assert "ORDER BY sort_order, id" in sql

    def test_move_to_front_moves_correctly(self):
        import data
        mock_member = {"id": 3, "queue_id": 1, "display_name": "C", "status": "active"}
        mock_sort = {"sort_order": 5}
        side_effects = [
            mock_member,
            mock_sort,
            None,
            None,
            None,
        ]
        with patch("data.fetchrow", AsyncMock(side_effect=side_effects)):
            with patch("data.execute", AsyncMock()):
                with patch("data._log_event", AsyncMock()):
                    result = asyncio.run(data.move_to_front(3, 1, 0))
                    assert result is not None
                    assert result["id"] == 3

    def test_join_queue_assigns_increasing_sort(self):
        import data
        with patch("data.get_queue", AsyncMock(return_value={"id": 1, "title": "Test", "is_active": True})):
            with patch("data.fetchrow") as mock_fetchrow:
                mock_fetchrow.side_effect = [
                    None,
                    {"next_sort": 3},
                    {"id": 10},
                    {"pos": 3},
                    None,
                ]
                with patch("data.execute", AsyncMock()):
                    with patch("data._log_event", AsyncMock()):
                        result = asyncio.run(data.join_queue(1, 100, "user", "Test"))
                        assert result == 3


class TestHandlerDispatch:
    def test_button_handler_admin_only_cmd_rejects_non_admin(self):
        import bot
        from permissions import _db_admins, _blocked
        _db_admins.clear()
        _blocked.clear()
        update = MagicMock()
        update.callback_query.data = "q:movefront:1"
        update.callback_query.from_user.id = 999
        update.effective_user.id = 999
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        context = MagicMock()
        context.user_data = {}
        with patch("bot.get_queue", AsyncMock(return_value={"id": 1, "title": "T", "is_active": True})):
            asyncio.run(bot.button_handler(update, context))
        args, _ = update.callback_query.edit_message_text.call_args
        assert "⛔" in args[0]

    def test_handle_member_action_movefront_requires_admin(self):
        import bot
        from permissions import _db_admins, _blocked
        _db_admins.clear()
        _blocked.clear()
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        with patch("bot.get_member_by_id", AsyncMock(return_value={
            "id": 1, "queue_id": 1, "telegram_user_id": 10, "display_name": "Test", "status": "active"
        })):
            with patch("bot.get_queue", AsyncMock(return_value={"id": 1, "title": "T", "is_active": True})):
                with patch("bot.move_to_front", AsyncMock()):
                    asyncio.run(bot.handle_member_action(query, None, "movefront", 1, 999))
                    query.edit_message_text.assert_called_once()
                    args, _ = query.edit_message_text.call_args
                    assert "⛔" in args[0]


class TestConcurrentAccess:
    def test_move_to_front_concurrent_calls(self):
        import data
        mock_member = {"id": 3, "queue_id": 1, "display_name": "C", "status": "active"}
        mock_sort = {"sort_order": 5}
        execute_call_count = [0]
        async def mock_execute(*args, **kwargs):
            execute_call_count[0] += 1
        with patch("data.fetchrow", AsyncMock(side_effect=[
            mock_member, mock_sort,
            mock_member, mock_sort,
            mock_member, mock_sort,
        ])):
            with patch("data.execute", mock_execute):
                with patch("data._log_event", AsyncMock()):
                    async def run_concurrent():
                        tasks = [
                            data.move_to_front(3, 1, 0),
                            data.move_to_front(3, 1, 0),
                            data.move_to_front(3, 1, 0),
                        ]
                        return await asyncio.gather(*tasks)
                    results = asyncio.run(run_concurrent())
                    assert len(results) == 3
                    assert all(r is not None for r in results)

    def test_many_concurrent_join_queue(self):
        import data
        queue_mock = {"id": 1, "title": "Test", "is_active": True}
        async def mock_fetchrow(query, *args):
            if "MAX(sort_order)" in query:
                return {"next_sort": 1}
            if "SELECT id FROM queue_members" in query:
                return None
            if "RETURNING id" in query:
                return {"id": hash(args)}
            if "COUNT" in query:
                return {"pos": 1}
            return None
        with patch("data.get_queue", AsyncMock(return_value=queue_mock)):
            with patch("data.fetchrow", mock_fetchrow):
                with patch("data.execute", AsyncMock()):
                    with patch("data._log_event", AsyncMock()):
                        async def run_many():
                            tasks = [
                                data.join_queue(1, i, f"user{i}", f"User{i}")
                                for i in range(50)
                            ]
                            return await asyncio.gather(*tasks)
                        results = asyncio.run(run_many())
                        assert len(results) == 50

    def test_rapid_error_handler_calls(self):
        from bot import error_handler
        async def rapid_errors():
            tasks = []
            for i in range(100):
                update = MagicMock()
                context = MagicMock()
                context.error = BadRequest("Message is not modified")
                update.effective_chat = None
                tasks.append(error_handler(update, context))
            await asyncio.gather(*tasks)
        asyncio.run(rapid_errors())


class TestKeyboardLoad:
    def test_queue_actions_keyboard_admin_has_movefront(self):
        import keyboards
        with patch("keyboards.is_admin", return_value=True):
            kb = keyboards.queue_actions_keyboard(1, 123)
        flat = []
        for row in kb.inline_keyboard:
            for btn in row:
                flat.append(btn.callback_data)
        assert any("movefront" in cb for cb in flat)

    def test_queue_actions_keyboard_non_admin_no_movefront(self):
        import keyboards
        with patch("keyboards.is_admin", return_value=False):
            kb = keyboards.queue_actions_keyboard(1, 999)
        flat = []
        for row in kb.inline_keyboard:
            for btn in row:
                flat.append(btn.callback_data)
        assert not any("movefront" in cb for cb in flat)

    def test_main_menu_keyboard_no_crash(self):
        from keyboards import main_menu_keyboard
        kb = main_menu_keyboard(0)
        assert kb is not None
        assert len(kb.inline_keyboard) > 0


class TestImportSanity:
    def test_bot_imports_cleanly(self):
        import bot
        assert hasattr(bot, "main")

    def test_data_has_all_functions(self):
        import data
        funcs = [
            "init_db", "get_queues", "get_queue", "create_queue",
            "delete_queue", "join_queue", "leave_queue",
            "mark_done", "mark_failed", "mark_missed",
            "return_to_queue", "remove_member",
            "get_active_members", "get_my_membership",
            "get_member_by_id", "move_to_front",
            "admin_clear_queue", "set_user_profile",
            "get_user_profile", "get_next_member",
            "get_all_profiles", "get_bot_admins",
            "add_bot_admin", "remove_bot_admin",
            "block_user", "unblock_user", "get_blocked_users",
        ]
        for f in funcs:
            assert hasattr(data, f), f"Missing: {f}"
