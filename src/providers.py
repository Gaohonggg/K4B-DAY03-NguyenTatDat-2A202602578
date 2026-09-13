"""
🔌 MULTI-PROVIDER LLM ADAPTER (Google Gemini, OpenAI & Offline Mock)

Hỗ trợ Native Tool Calling và duy trì Observation giữa các vòng ReAct.
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        """Cho phép chạy Mock Provider trước khi cài python-dotenv."""
        return False


if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()

ToolContext = List[Dict[str, Any]]


def _build_context_prompt(prompt: str, tool_context: Optional[ToolContext]) -> str:
    """Ghép Observation đã có vào lượt suy luận kế tiếp."""
    if not tool_context:
        return prompt

    history_lines = []
    for index, item in enumerate(tool_context, start=1):
        history_lines.append(
            f"Bước {index}: tool={item['tool_name']}, "
            f"arguments={json.dumps(item['arguments'], ensure_ascii=False)}, "
            f"observation={json.dumps(item['observation'], ensure_ascii=False)}"
        )

    return (
        f"YÊu CẦU GỐC:\n{prompt}\n\n"
        "LỊCH SỬ TOOL CALL VÀ OBSERVATION:\n"
        + "\n".join(history_lines)
        + "\n\nHãy tiếp tục bước còn thiếu. Không gọi lại tool đã hoàn thành "
        "nếu Observation đã đủ để trả lời."
    )


class BaseLLMProvider:
    """Interface cơ sở cho các LLM Provider hỗ trợ Native Tool Calling."""

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        tool_context: Optional[ToolContext] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError


class MockOfflineProvider(BaseLLMProvider):
    """Provider tất định dùng để kiểm thử ReAct Loop không cần API Key."""

    def __init__(self):
        self.model_name = "Offline-Mock-VinBus-2026"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return (
            "[Mock Chatbot Response]: VinBus cung cấp dịch vụ xe buýt điện và vé tháng. "
            "Chatbot baseline chỉ giải đáp thông tin chung, không tra cứu hoặc đăng ký trên hệ thống."
        )

    @staticmethod
    def _extract_route_id(prompt: str) -> Optional[str]:
        match = re.search(r"\bV\d{2,3}\b", prompt, flags=re.IGNORECASE)
        return match.group(0).upper() if match else None

    @staticmethod
    def _extract_customer_id(prompt: str) -> Optional[str]:
        match = re.search(r"\bKH\d{7}\b", prompt, flags=re.IGNORECASE)
        return match.group(0).upper() if match else None

    @staticmethod
    def _extract_month(prompt: str) -> Optional[str]:
        iso_match = re.search(r"\b(\d{4})-(0[1-9]|1[0-2])\b", prompt)
        if iso_match:
            return iso_match.group(0)

        local_match = re.search(r"\b(0?[1-9]|1[0-2])/(\d{4})\b", prompt)
        if local_match:
            month_number, year = local_match.groups()
            return f"{year}-{int(month_number):02d}"
        return None

    @staticmethod
    def _extract_journey(prompt: str) -> Optional[Dict[str, str]]:
        match = re.search(
            r"\btừ\s+(.+?)\s+đến\s+(.+?)(?:[.,]|\s+hãy\b|\s+rồi\b|$)",
            prompt,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return {"query": match.group(1).strip(), "destination": match.group(2).strip()}

    @staticmethod
    def _final_from_observation(tool_name: str, observation: Dict[str, Any]) -> str:
        status = observation.get("status")
        if status != "SUCCESS":
            return observation.get("message", "Yêu cầu chưa thể hoàn tất.")

        if tool_name == "route_lookup":
            data = observation.get("data", {})
            routes = data.get("routes", [])
            if not routes:
                return observation.get("message", "Không có dữ liệu tuyến phù hợp.")
            route = routes[0]
            stops = " → ".join(route.get("stops", []))
            return (
                f"Tuyến đề xuất là {route['route_id']} ({route['route_name']}). "
                f"Lộ trình: {stops}. Thời gian hoạt động: {route['operating_hours']}; "
                f"tần suất {route['frequency_minutes']} phút/chuyến; "
                f"giá vé tháng {route['monthly_pass_price_vnd']:,} VNĐ."
            )

        registration = observation.get("data", {})
        return (
            f"Đăng ký thành công vé tháng {registration.get('month')} cho "
            f"{registration.get('customer_id')} trên tuyến {registration.get('route_id')}. "
            f"Mã đăng ký: {registration.get('registration_id')}; "
            f"giá: {registration.get('price_vnd', 0):,} VNĐ."
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        tool_context: Optional[ToolContext] = None,
    ) -> Dict[str, Any]:
        context = tool_context or []
        customer_id = self._extract_customer_id(prompt)
        month = self._extract_month(prompt)
        asks_registration = "đăng ký" in prompt.casefold() and "vé tháng" in prompt.casefold()

        if context:
            last_call = context[-1]
            last_tool = last_call["tool_name"]
            observation = last_call["observation"]

            if observation.get("status") != "SUCCESS":
                return {
                    "type": "text",
                    "content": self._final_from_observation(last_tool, observation),
                    "thought": "Observation báo yêu cầu không thành công; phản hồi đúng lỗi và dừng.",
                }

            if last_tool == "route_lookup" and asks_registration:
                recommended_route_id = observation.get("data", {}).get("recommended_route_id")
                if customer_id and month and recommended_route_id:
                    return {
                        "type": "tool_call",
                        "tool_name": "register_monthly_pass",
                        "arguments": {
                            "customer_id": customer_id,
                            "route_id": recommended_route_id,
                            "month": month,
                        },
                        "thought": (
                            f"Đã xác định tuyến {recommended_route_id} từ Observation; "
                            "tiếp tục đăng ký vé tháng."
                        ),
                    }

            return {
                "type": "text",
                "content": self._final_from_observation(last_tool, observation),
                "thought": "Dữ liệu từ tool đã đủ để tổng hợp câu trả lời cuối cùng.",
            }

        route_id = self._extract_route_id(prompt)
        journey = self._extract_journey(prompt)

        if asks_registration and route_id:
            if not customer_id or not month:
                return {
                    "type": "text",
                    "content": "Vui lòng cung cấp đủ mã khách hàng và tháng đăng ký.",
                    "thought": "Thiếu thông tin bắt buộc để đăng ký vé tháng.",
                }
            return {
                "type": "tool_call",
                "tool_name": "register_monthly_pass",
                "arguments": {"customer_id": customer_id, "route_id": route_id, "month": month},
                "thought": "Đã có đủ mã khách hàng, tuyến và tháng; gọi tool đăng ký vé.",
            }

        if journey:
            return {
                "type": "tool_call",
                "tool_name": "route_lookup",
                "arguments": journey,
                "thought": "Cần tra cứu tuyến phù hợp giữa điểm đi và điểm đến trước.",
            }

        if route_id:
            return {
                "type": "tool_call",
                "tool_name": "route_lookup",
                "arguments": {"query": route_id},
                "thought": f"Người dùng cần dữ liệu cụ thể của tuyến {route_id}.",
            }

        return {
            "type": "text",
            "content": (
                "VinBus cung cấp dịch vụ xe buýt điện và hỗ trợ đăng ký vé tháng. "
                "Bạn có thể cung cấp mã tuyến hoặc điểm đi - điểm đến để được hỗ trợ."
            ),
            "thought": "Câu hỏi mang tính giới thiệu chung nên không cần gọi tool.",
        }


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider sử dụng Native Tool Calling."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env."
        try:
            from google import genai

            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(model=self.model_name, contents=contents)
            return response.text
        except Exception as exc:
            return f"[Gemini Exception]: {exc}"

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        tool_context: Optional[ToolContext] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, tool_context
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            function_declarations = [
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool["parameters"],
                }
                for tool in tools_schema
                if tool.get("name") and tool.get("parameters")
            ]
            config = types.GenerateContentConfig(
                system_instruction=system_prompt or None,
                tools=[{"function_declarations": function_declarations}],
                temperature=0.2,
            )
            response = client.models.generate_content(
                model=self.model_name,
                contents=_build_context_prompt(prompt, tool_context),
                config=config,
            )
            if response.function_calls:
                call = response.function_calls[0]
                arguments = dict(call.args) if getattr(call, "args", None) else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.name,
                    "arguments": arguments,
                    "thought": f"Gemini chọn tool '{call.name}' cho bước tiếp theo.",
                }
            return {
                "type": "text",
                "content": response.text or "",
                "thought": "Gemini đã đủ dữ liệu để trả lời mà không cần gọi thêm tool.",
            }
        except Exception as exc:
            print(f"⚠️ [Gemini API Warning]: {exc}. Tự động fallback về Mock Offline.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, tool_context
            )


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider sử dụng Native Tool Calling."""

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env."
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(model=self.model_name, messages=messages)
            return response.choices[0].message.content or ""
        except Exception as exc:
            return f"[OpenAI Exception]: {exc}"

    def generate_with_tools(
        self,
        prompt: str,
        tools_schema: List[Dict[str, Any]],
        system_prompt: str = "",
        tool_context: Optional[ToolContext] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, tool_context
            )

        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    },
                }
                for tool in tools_schema
                if tool.get("name")
            ]
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append(
                {"role": "user", "content": _build_context_prompt(prompt, tool_context)}
            )
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.2,
            )
            message = response.choices[0].message
            if message.tool_calls:
                call = message.tool_calls[0]
                arguments = json.loads(call.function.arguments) if call.function.arguments else {}
                return {
                    "type": "tool_call",
                    "tool_name": call.function.name,
                    "arguments": arguments,
                    "thought": f"OpenAI chọn tool '{call.function.name}' cho bước tiếp theo.",
                }
            return {
                "type": "text",
                "content": message.content or "",
                "thought": "OpenAI đã đủ dữ liệu để trả lời mà không cần gọi thêm tool.",
            }
        except Exception as exc:
            print(f"⚠️ [OpenAI API Warning]: {exc}. Tự động fallback về Mock Offline.")
            return MockOfflineProvider().generate_with_tools(
                prompt, tools_schema, system_prompt, tool_context
            )


def get_llm_provider() -> BaseLLMProvider:
    """Khởi tạo Provider theo biến môi trường LLM_PROVIDER."""
    provider_type = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider_type == "gemini":
        key = os.getenv("GEMINI_API_KEY")
        return GeminiProvider() if key and key != "your_gemini_api_key_here" else MockOfflineProvider()
    if provider_type == "openai":
        key = os.getenv("OPENAI_API_KEY")
        return OpenAIProvider() if key and key != "your_openai_api_key_here" else MockOfflineProvider()
    return MockOfflineProvider()
