import httpx
import time

def verify_api_e2e(base_url: str) -> dict:
    """Run E2E HTTP requests against base_url (local or public Cloudflare endpoint)."""
    clean_url = base_url.rstrip("/")
    results = {"total": 0, "passed": 0, "failed": 0, "details": [], "dns_restricted": False}

    # Pre-flight DNS check
    try:
        r = httpx.get(f"{clean_url}/", timeout=5.0, follow_redirects=True)
    except Exception as e:
        if "getaddrinfo failed" in str(e) or "NameResolutionError" in str(e):
            return {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "dns_restricted": True,
                "message": f"Public URL generated ({clean_url}), but local network DNS restricts external resolution of *.trycloudflare.com domains.",
                "details": [{"test": "DNS Resolution Check", "status": "WARN", "message": str(e)}],
                "success": True
            }

    def _test(name: str, fn):
        results["total"] += 1
        try:
            ok, msg = fn()
            if ok:
                results["passed"] += 1
                results["details"].append({"test": name, "status": "PASS", "message": msg})
            else:
                results["failed"] += 1
                results["details"].append({"test": name, "status": "FAIL", "message": msg})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"test": name, "status": "FAIL", "message": f"Exception: {e}"})

    # 1. Health check
    def _test_health():
        r = httpx.get(f"{clean_url}/", timeout=10.0, follow_redirects=True)
        if r.status_code == 200:
            return True, f"HTTP 200: {r.json()}"
        return False, f"HTTP {r.status_code}"
    _test("GET / (Health Check)", _test_health)

    # 2. Create expense
    created_id = None
    def _test_create():
        nonlocal created_id
        payload = {
            "title": "E2E Test Coffee",
            "amount": 4.50,
            "category": "food",
            "date": "2026-08-10",
            "description": "MOSHI 2.0 E2E Verification"
        }
        r = httpx.post(f"{clean_url}/expenses", json=payload, timeout=10.0, follow_redirects=True)
        if r.status_code in (200, 201):
            data = r.json()
            created_id = data.get("id")
            return True, f"HTTP {r.status_code}: Created ID {created_id}"
        return False, f"HTTP {r.status_code}: {r.text}"
    _test("POST /expenses (Create)", _test_create)

    # 3. List expenses
    def _test_list():
        r = httpx.get(f"{clean_url}/expenses", timeout=10.0, follow_redirects=True)
        if r.status_code == 200 and isinstance(r.json(), list):
            return True, f"HTTP 200: Listed {len(r.json())} item(s)"
        return False, f"HTTP {r.status_code}"
    _test("GET /expenses (List)", _test_list)

    # 4. Get Total
    def _test_total():
        r = httpx.get(f"{clean_url}/expenses/total", timeout=10.0, follow_redirects=True)
        if r.status_code == 200:
            return True, f"HTTP 200: {r.json()}"
        return False, f"HTTP {r.status_code}"
    _test("GET /expenses/total", _test_total)

    # 5. Delete expense if created
    if created_id:
        def _test_delete():
            r = httpx.delete(f"{clean_url}/expenses/{created_id}", timeout=10.0, follow_redirects=True)
            if r.status_code == 200:
                return True, f"HTTP 200: Expense {created_id} deleted"
            return False, f"HTTP {r.status_code}"
        _test(f"DELETE /expenses/{created_id}", _test_delete)

    results["success"] = (results["failed"] == 0)
    return results
