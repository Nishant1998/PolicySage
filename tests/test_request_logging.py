import unittest
from unittest.mock import patch

from app.core import observability
from app.main import RequestObservation


class RequestObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_is_summarized_after_final_body(self):
        async def app(scope, receive, send):
            observation = observability.current_request.get()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"first", "more_body": True})
            observation.update(llm_calls=1, input_tokens=3, output_tokens=2, cost_complete=False)
            await send({"type": "http.response.body", "body": b"last", "more_body": False})

        async def receive():
            return {"type": "http.request", "body": b""}

        messages = []
        async def send(message):
            messages.append(message)

        with patch.object(observability, "event") as event:
            await RequestObservation(app)({"type": "http", "path": "/api/chat", "method": "POST"}, receive, send)
        summary = [call.kwargs for call in event.call_args_list if call.args[0] == "request_finished"][0]
        self.assertEqual((summary["http_status"], summary["method"], summary["total_tokens"]), (200, "POST", 5))
        self.assertIsNone(summary["estimated_cost_usd"])
        self.assertTrue(any(key == b"x-request-id" for key, _ in messages[0]["headers"]))
        self.assertIsNone(observability.current_request.get())

    async def test_disconnect_is_recorded(self):
        async def app(scope, receive, send):
            await receive()
        async def receive():
            return {"type": "http.disconnect"}
        async def send(message):
            pass
        with patch.object(observability, "event") as event:
            await RequestObservation(app)({"type": "http", "path": "/api/chat", "method": "POST"}, receive, send)
        summary = [call.kwargs for call in event.call_args_list if call.args[0] == "request_finished"][0]
        self.assertEqual(summary["error_type"], "ClientDisconnected")


if __name__ == "__main__":
    unittest.main()
