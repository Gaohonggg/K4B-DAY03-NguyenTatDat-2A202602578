"""
🚀 VINBUS REACT AGENT APPLICATION

So sánh Chatbot Baseline và ReAct Agent kết nối VinBus MCP Server,
đồng thời xuất Waterfall Trace phục vụ nghiệm thu.
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        """Cho phép chạy Mock Provider trước khi cài python-dotenv."""
        return False


sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from mcp_server import MCPVinBusServer
from prompts import CHATBOT_BASELINE_PROMPT, MAX_ITERATIONS, REACT_AGENT_SYSTEM_PROMPT
from providers import BaseLLMProvider, get_llm_provider


load_dotenv()


def load_test_cases() -> List[Dict[str, Any]]:
    """Tải 5 test cases từ config chính hoặc file example."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    if not os.path.exists(config_path):
        example_path = os.path.join(base_dir, "config", "test_cases.example.json")
        if not os.path.exists(example_path):
            raise FileNotFoundError("Không tìm thấy file cấu hình test cases.")
        print("⚠️ [CONFIG]: Đang dùng config/test_cases.example.json.")
        config_path = example_path

    with open(config_path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_waterfall_trace(trace_data: List[Dict[str, Any]]) -> str:
    """Ghi Waterfall Trace Log ra docs/trace_waterfall.json."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    trace_path = os.path.join(base_dir, "docs", "trace_waterfall.json")
    with open(trace_path, "w", encoding="utf-8") as file:
        json.dump(trace_data, file, ensure_ascii=False, indent=2)
    print(f"📊 [OBSERVABILITY]: Đã lưu {len(trace_data)} sự kiện tại '{trace_path}'.")
    return trace_path


def run_baseline_chatbot(user_query: str, provider: BaseLLMProvider) -> str:
    """Chạy Chatbot Baseline không có tool."""
    print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")
    response = provider.generate(user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f"🤖 Chatbot phản hồi:\n{response}")
    return response


def run_react_agent(
    user_query: str,
    provider: BaseLLMProvider,
    mcp_server: MCPVinBusServer,
    test_case_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Chạy vòng lặp Thought -> Action -> Observation -> Final Answer."""
    print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")

    trace_logs: List[Dict[str, Any]] = []
    tool_context: List[Dict[str, Any]] = []
    tools_list = mcp_server.list_tools()
    previous_calls = set()

    for iteration in range(1, MAX_ITERATIONS + 1):
        started_at = time.perf_counter()
        print(f"\n--- 🔄 ReAct Loop (Iteration {iteration}/{MAX_ITERATIONS}) ---")

        llm_response = provider.generate_with_tools(
            user_query,
            tools_list,
            system_prompt=REACT_AGENT_SYSTEM_PROMPT,
            tool_context=tool_context,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        thought = llm_response.get("thought", "Đang xác định bước xử lý tiếp theo.")
        print(f"🧠 [Thought]: {thought}")

        if llm_response.get("type") == "text":
            final_content = llm_response.get("content", "")
            print(f"🏁 [Final Answer]: {final_content}")
            trace_logs.append(
                {
                    "test_case_id": test_case_id,
                    "iteration": iteration,
                    "action_type": "FINAL_ANSWER",
                    "thought": thought,
                    "output": final_content,
                    "latency_ms": latency_ms,
                }
            )
            return trace_logs

        if llm_response.get("type") != "tool_call":
            error_message = "Provider trả về response type không hợp lệ."
            print(f"❌ [Final Answer]: {error_message}")
            trace_logs.append(
                {
                    "test_case_id": test_case_id,
                    "iteration": iteration,
                    "action_type": "FINAL_ANSWER",
                    "thought": "Không thể tiếp tục do response không hợp lệ.",
                    "output": error_message,
                    "latency_ms": latency_ms,
                }
            )
            return trace_logs

        tool_name = llm_response.get("tool_name", "")
        arguments = llm_response.get("arguments", {})
        call_signature = (tool_name, json.dumps(arguments, ensure_ascii=False, sort_keys=True))
        if call_signature in previous_calls:
            error_message = f"Dừng vòng lặp do tool '{tool_name}' bị gọi lặp với cùng tham số."
            print(f"❌ [Final Answer]: {error_message}")
            trace_logs.append(
                {
                    "test_case_id": test_case_id,
                    "iteration": iteration,
                    "action_type": "FINAL_ANSWER",
                    "thought": "Phát hiện tool call lặp; dừng an toàn để tránh vòng lặp vô hạn.",
                    "output": error_message,
                    "latency_ms": latency_ms,
                }
            )
            return trace_logs
        previous_calls.add(call_signature)

        print(f"🛠️ [Action]: {tool_name}({arguments})")
        mcp_started_at = time.perf_counter()
        mcp_result = mcp_server.call_tool(tool_name, arguments)
        tool_latency_ms = round((time.perf_counter() - mcp_started_at) * 1000, 2)
        observation = mcp_result.get("result", {})
        print(f"👁️ [Observation]: {json.dumps(observation, ensure_ascii=False)}")

        trace_logs.append(
            {
                "test_case_id": test_case_id,
                "iteration": iteration,
                "action_type": "TOOL_EXECUTION",
                "thought": thought,
                "action": {"tool_name": tool_name, "arguments": arguments},
                "observation": observation,
                "llm_latency_ms": latency_ms,
                "tool_latency_ms": tool_latency_ms,
            }
        )
        tool_context.append(
            {
                "tool_name": tool_name,
                "arguments": arguments,
                "observation": observation,
            }
        )

    final_message = f"Không thể hoàn tất yêu cầu sau {MAX_ITERATIONS} vòng ReAct."
    print(f"❌ [Final Answer]: {final_message}")
    trace_logs.append(
        {
            "test_case_id": test_case_id,
            "iteration": MAX_ITERATIONS,
            "action_type": "FINAL_ANSWER",
            "thought": "Đã đạt giới hạn vòng lặp.",
            "output": final_message,
            "latency_ms": 0.0,
        }
    )
    return trace_logs


def evaluate_test_case(
    test_case: Dict[str, Any], trace_logs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """So sánh trace thực tế với tool sequence và status mong đợi."""
    tool_events = [event for event in trace_logs if event["action_type"] == "TOOL_EXECUTION"]
    actual_tools = [event["action"]["tool_name"] for event in tool_events]
    actual_statuses = [event["observation"].get("status") for event in tool_events]
    expected_tools = test_case.get("expected_tools", [])
    expected_statuses = test_case.get("expected_statuses", [])
    has_final_answer = any(event["action_type"] == "FINAL_ANSWER" for event in trace_logs)

    passed = (
        actual_tools == expected_tools
        and actual_statuses == expected_statuses
        and has_final_answer
    )
    return {
        "test_case_id": test_case["id"],
        "passed": passed,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
        "expected_statuses": expected_statuses,
        "actual_statuses": actual_statuses,
        "has_final_answer": has_final_answer,
    }


def run_test_suite(
    tests: List[Dict[str, Any]], provider: BaseLLMProvider, mcp_server: MCPVinBusServer
) -> List[Dict[str, Any]]:
    """Chạy test suite, chấm PASS/FAIL thực tế và lưu trace."""
    all_traces: List[Dict[str, Any]] = []
    results: List[Dict[str, Any]] = []

    for test_case in tests:
        print("\n==================================================")
        print(
            f"🧪 [{test_case['id']}] {test_case['type']} "
            f"(Độ phức tạp: {test_case['complexity']})"
        )
        print(f"📌 Kỳ vọng: {test_case['expected_behavior']}")
        trace_logs = run_react_agent(
            test_case["question"], provider, mcp_server, test_case_id=test_case["id"]
        )
        result = evaluate_test_case(test_case, trace_logs)
        results.append(result)
        all_traces.extend(trace_logs)
        print(
            f"{'\u2705 PASS' if result['passed'] else '\u274c FAIL'} | "
            f"Tools: {result['actual_tools']} | Statuses: {result['actual_statuses']}"
        )

    pass_count = sum(result["passed"] for result in results)
    tool_call_count = sum(
        event["action_type"] == "TOOL_EXECUTION" for event in all_traces
    )
    print("\n==================================================")
    print(f"📊 [TEST SUITE]: {pass_count}/{len(tests)} PASS | {tool_call_count} tool calls")
    save_waterfall_trace(all_traces)
    return results


def main() -> None:
    print("==========================================================")
    print("🚌 VINBUS CUSTOMER SERVICE: CHATBOT VS REACT AGENT")
    print("==========================================================")

    provider = get_llm_provider()
    mcp_server = MCPVinBusServer()
    tests = load_test_cases()

    print(f"🔌 LLM Provider: {provider.__class__.__name__}")
    print(f"🌐 MCP Server: {mcp_server.server_name}")
    print(f"✅ Đã tải {len(tests)} Test Cases.")

    if "--interactive" in sys.argv:
        print("\n🎮 [INTERACTIVE MODE] Gợi ý:")
        print("   - Hãy tra cứu lộ trình tuyến VinBus V01.")
        print("   - Đăng ký vé tháng 10/2026 cho KH2026001 trên tuyến V02.")
        print("   - Tìm tuyến từ Vinhomes Ocean Park đến Vincom Bà Triệu rồi đăng ký vé.")
        print("   - Gõ 'exit' hoặc 'quit' để thoát.\n")
        while True:
            try:
                user_input = input("👤 Khách hàng: ").strip()
                if not user_input or user_input.casefold() in {"exit", "quit"}:
                    print("👋 Kết thúc phiên trò chuyện.")
                    break
                logs = run_react_agent(user_input, provider, mcp_server)
                save_waterfall_trace(logs)
            except (KeyboardInterrupt, EOFError):
                print("\n👋 Đã thoát phiên tương tác.")
                break
        return

    if "--all" in sys.argv:
        run_test_suite(tests, provider, mcp_server)
        return

    print("\nℹ️ HƯỚNG DẪN:")
    print("  1. Chat trực tiếp: python src/app.py --interactive")
    print("  2. Chạy 5 test cases: python src/app.py --all\n")
    sample_test = tests[1]
    print(f"--- 🏁 DEMO {sample_test['id']}: Tra cứu tuyến VinBus ---")
    logs = run_react_agent(
        sample_test["question"], provider, mcp_server, test_case_id=sample_test["id"]
    )
    save_waterfall_trace(logs)


if __name__ == "__main__":
    main()
