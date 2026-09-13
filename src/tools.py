"""
🛠️ VINBUS TOOL DEFINITIONS & EXECUTION BACKEND

Chứa Tool Schemas chuẩn JSON Schema, mock data và execution layer phục vụ
VinBus MCP Server.
"""

import json
import re
import unicodedata
from typing import Any, Dict, List


# ==============================================================================
# 1. TOOL SCHEMAS
# ==============================================================================

TOOLS_SCHEMA = [
    {
        "name": "route_lookup",
        "description": (
            "Tra cứu thông tin một tuyến VinBus theo mã tuyến, hoặc tìm tuyến phù hợp "
            "giữa điểm xuất phát và điểm đến."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Mã tuyến cần tra cứu (ví dụ: 'V01') hoặc điểm xuất phát "
                        "khi tìm hành trình (ví dụ: 'Vinhomes Ocean Park')."
                    ),
                },
                "destination": {
                    "type": "string",
                    "description": (
                        "Điểm đến khi tìm hành trình. Bỏ qua trường này nếu query là mã tuyến."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "register_monthly_pass",
        "description": (
            "Đăng ký vé tháng VinBus cho khách hàng trên một tuyến đã xác định. "
            "Chỉ gọi sau khi đã biết chính xác mã khách hàng, mã tuyến và tháng áp dụng."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Mã khách hàng VinBus (ví dụ: 'KH2026001').",
                    "pattern": "^KH[0-9]{7}$",
                },
                "route_id": {
                    "type": "string",
                    "description": "Mã tuyến VinBus cần đăng ký (ví dụ: 'V01').",
                    "pattern": "^V[0-9]{2,3}$",
                },
                "month": {
                    "type": "string",
                    "description": "Tháng áp dụng vé theo định dạng YYYY-MM (ví dụ: '2026-10').",
                    "pattern": "^[0-9]{4}-(0[1-9]|1[0-2])$",
                },
            },
            "required": ["customer_id", "route_id", "month"],
            "additionalProperties": False,
        },
    },
]


# ==============================================================================
# 2. MOCK DATA
# ==============================================================================

MOCK_ROUTES: Dict[str, Dict[str, Any]] = {
    "V01": {
        "route_id": "V01",
        "route_name": "Vinhomes Ocean Park - Bến xe Mỹ Đình",
        "origin": "Vinhomes Ocean Park",
        "destination": "Bến xe Mỹ Đình",
        "stops": [
            "Vinhomes Ocean Park",
            "Aeon Mall Long Biên",
            "Nhà hát Lớn Hà Nội",
            "Vincom Bà Triệu",
            "Royal City",
            "Bến xe Mỹ Đình",
        ],
        "operating_hours": "05:00-22:00",
        "frequency_minutes": 15,
        "monthly_pass_price_vnd": 200000,
        "status": "ACTIVE",
    },
    "V02": {
        "route_id": "V02",
        "route_name": "Vinhomes Smart City - Times City",
        "origin": "Vinhomes Smart City",
        "destination": "Times City",
        "stops": [
            "Vinhomes Smart City",
            "Trung tâm Hội nghị Quốc gia",
            "Ngã Tư Sở",
            "Công viên Thống Nhất",
            "Times City",
        ],
        "operating_hours": "05:30-21:30",
        "frequency_minutes": 20,
        "monthly_pass_price_vnd": 200000,
        "status": "ACTIVE",
    },
    "V03": {
        "route_id": "V03",
        "route_name": "Vinhomes Ocean Park - Sân bay Nội Bài",
        "origin": "Vinhomes Ocean Park",
        "destination": "Sân bay Nội Bài",
        "stops": [
            "Vinhomes Ocean Park",
            "Cầu Chương Dương",
            "Hồ Tây",
            "Cầu Nhật Tân",
            "Sân bay Nội Bài",
        ],
        "operating_hours": "05:00-23:00",
        "frequency_minutes": 30,
        "monthly_pass_price_vnd": 250000,
        "status": "ACTIVE",
    },
}

MOCK_CUSTOMERS: Dict[str, Dict[str, str]] = {
    "KH2026001": {
        "customer_id": "KH2026001",
        "full_name": "Nguyễn Minh Anh",
        "phone": "0900000001",
        "status": "ACTIVE",
    },
    "KH2026002": {
        "customer_id": "KH2026002",
        "full_name": "Trần Hoàng Nam",
        "phone": "0900000002",
        "status": "ACTIVE",
    },
    "KH2026003": {
        "customer_id": "KH2026003",
        "full_name": "Lê Thu Hà",
        "phone": "0900000003",
        "status": "INACTIVE",
    },
}

# Kho mock trong bộ nhớ; dữ liệu được khởi tạo lại mỗi khi chạy chương trình.
MOCK_MONTHLY_PASSES: Dict[str, Dict[str, Any]] = {
    "PASS-KH2026001-V01-2026-09": {
        "registration_id": "PASS-KH2026001-V01-2026-09",
        "customer_id": "KH2026001",
        "route_id": "V01",
        "month": "2026-09",
        "status": "ACTIVE",
    }
}


# ==============================================================================
# 3. DATA NORMALIZATION & VALIDATION HELPERS
# ==============================================================================

def _normalize_text(value: str) -> str:
    """Chuẩn hóa chuỗi để so khớp tên địa điểm không phân biệt dấu."""
    normalized = unicodedata.normalize("NFD", value.strip().casefold())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def _normalize_month(month: str) -> str:
    """Chấp nhận YYYY-MM hoặc MM/YYYY và trả về YYYY-MM."""
    value = month.strip()
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        return value

    match = re.fullmatch(r"(0?[1-9]|1[0-2])/(\d{4})", value)
    if match:
        month_number, year = match.groups()
        return f"{year}-{int(month_number):02d}"

    raise ValueError("Tháng áp dụng phải có định dạng YYYY-MM hoặc MM/YYYY.")


def _route_contains_location(route: Dict[str, Any], location: str) -> bool:
    target = _normalize_text(location)
    return any(
        target in _normalize_text(stop) or _normalize_text(stop) in target
        for stop in route["stops"]
    )


def _public_route_data(route: Dict[str, Any]) -> Dict[str, Any]:
    """Trả về bản sao dữ liệu tuyến an toàn cho Tool response."""
    return {
        "route_id": route["route_id"],
        "route_name": route["route_name"],
        "origin": route["origin"],
        "destination": route["destination"],
        "stops": list(route["stops"]),
        "operating_hours": route["operating_hours"],
        "frequency_minutes": route["frequency_minutes"],
        "monthly_pass_price_vnd": route["monthly_pass_price_vnd"],
        "status": route["status"],
    }


# ==============================================================================
# 4. TOOL EXECUTION FUNCTIONS
# ==============================================================================

def execute_route_lookup(query: str, destination: str = "") -> str:
    """Tra cứu tuyến theo mã hoặc tìm tuyến theo hành trình."""
    query_value = query.strip()
    if not query_value:
        return json.dumps(
            {"status": "INVALID_REQUEST", "message": "Nội dung tra cứu không được để trống."},
            ensure_ascii=False,
        )

    # Query có dạng Vxx được hiểu là tra cứu theo mã tuyến.
    if re.fullmatch(r"V\d{2,3}", query_value.upper()):
        route_id = query_value.upper()
        route = MOCK_ROUTES.get(route_id)
        if not route:
            return json.dumps(
                {
                    "status": "NOT_FOUND",
                    "message": f"Không tìm thấy tuyến VinBus có mã '{route_id}'.",
                    "query": {"route_id": route_id},
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "status": "SUCCESS",
                "message": f"Đã tìm thấy thông tin tuyến {route_id}.",
                "query": {"route_id": route_id},
                "data": {
                    "match_count": 1,
                    "recommended_route_id": route_id,
                    "routes": [_public_route_data(route)],
                },
            },
            ensure_ascii=False,
        )

    if not destination.strip():
        return json.dumps(
            {
                "status": "INVALID_REQUEST",
                "message": "Cần cung cấp điểm đến khi tìm tuyến theo hành trình.",
                "query": {"origin": query_value, "destination": destination},
            },
            ensure_ascii=False,
        )

    matched_routes: List[Dict[str, Any]] = []
    for route in MOCK_ROUTES.values():
        if route["status"] != "ACTIVE":
            continue
        if _route_contains_location(route, query_value) and _route_contains_location(route, destination):
            matched_routes.append(_public_route_data(route))

    if not matched_routes:
        return json.dumps(
            {
                "status": "NOT_FOUND",
                "message": (
                    f"Không tìm thấy tuyến VinBus phù hợp từ '{query_value}' "
                    f"đến '{destination.strip()}'."
                ),
                "query": {"origin": query_value, "destination": destination.strip()},
            },
            ensure_ascii=False,
        )

    recommended_route_id = matched_routes[0]["route_id"]
    return json.dumps(
        {
            "status": "SUCCESS",
            "message": (
                f"Đã tìm thấy {len(matched_routes)} tuyến phù hợp; "
                f"đề xuất tuyến {recommended_route_id}."
            ),
            "query": {"origin": query_value, "destination": destination.strip()},
            "data": {
                "match_count": len(matched_routes),
                "recommended_route_id": recommended_route_id,
                "routes": matched_routes,
            },
        },
        ensure_ascii=False,
    )


def execute_register_monthly_pass(customer_id: str, route_id: str, month: str) -> str:
    """Thực thi đăng ký vé tháng VinBus trên mock database."""
    normalized_customer_id = customer_id.strip().upper()
    normalized_route_id = route_id.strip().upper()

    customer = MOCK_CUSTOMERS.get(normalized_customer_id)
    if not customer:
        return json.dumps(
            {
                "status": "NOT_FOUND",
                "message": f"Không tìm thấy khách hàng '{normalized_customer_id}'.",
            },
            ensure_ascii=False,
        )
    if customer["status"] != "ACTIVE":
        return json.dumps(
            {
                "status": "INVALID_REQUEST",
                "message": f"Tài khoản khách hàng '{normalized_customer_id}' không hoạt động.",
            },
            ensure_ascii=False,
        )

    route = MOCK_ROUTES.get(normalized_route_id)
    if not route or route["status"] != "ACTIVE":
        return json.dumps(
            {
                "status": "NOT_FOUND",
                "message": f"Không tìm thấy tuyến VinBus hoạt động '{normalized_route_id}'.",
            },
            ensure_ascii=False,
        )

    try:
        normalized_month = _normalize_month(month)
    except ValueError as exc:
        return json.dumps(
            {"status": "INVALID_REQUEST", "message": str(exc)},
            ensure_ascii=False,
        )

    registration_id = f"PASS-{normalized_customer_id}-{normalized_route_id}-{normalized_month}"
    if registration_id in MOCK_MONTHLY_PASSES:
        return json.dumps(
            {
                "status": "CONFLICT",
                "message": (
                    f"Khách hàng {normalized_customer_id} đã đăng ký vé tháng "
                    f"cho tuyến {normalized_route_id} trong tháng {normalized_month}."
                ),
                "data": MOCK_MONTHLY_PASSES[registration_id],
            },
            ensure_ascii=False,
        )

    registration = {
        "registration_id": registration_id,
        "customer_id": normalized_customer_id,
        "customer_name": customer["full_name"],
        "route_id": normalized_route_id,
        "route_name": route["route_name"],
        "month": normalized_month,
        "price_vnd": route["monthly_pass_price_vnd"],
        "status": "REGISTERED",
    }
    MOCK_MONTHLY_PASSES[registration_id] = registration

    return json.dumps(
        {
            "status": "SUCCESS",
            "message": (
                f"Đăng ký vé tháng {normalized_month} thành công cho khách hàng "
                f"{normalized_customer_id} trên tuyến {normalized_route_id}."
            ),
            "data": registration,
        },
        ensure_ascii=False,
    )


# ==============================================================================
# 5. TOOL ROUTER
# ==============================================================================

TOOL_ROUTER = {
    "route_lookup": execute_route_lookup,
    "register_monthly_pass": execute_register_monthly_pass,
}


def dispatch_tool_call(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Trung chuyển yêu cầu thực thi đến VinBus tool tương ứng."""
    tool = TOOL_ROUTER.get(tool_name)
    if not tool:
        return json.dumps(
            {"status": "UNKNOWN_TOOL", "message": f"Tool '{tool_name}' không tồn tại."},
            ensure_ascii=False,
        )

    try:
        return tool(**arguments)
    except TypeError as exc:
        return json.dumps(
            {"status": "INVALID_REQUEST", "message": f"Tham số tool không hợp lệ: {exc}"},
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps(
            {"status": "EXECUTION_ERROR", "message": f"Lỗi thực thi tool: {exc}"},
            ensure_ascii=False,
        )
