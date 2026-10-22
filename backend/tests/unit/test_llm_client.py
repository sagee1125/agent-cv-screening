# Confirms job-ad and CV model calls use different wait limits.
from __future__ import annotations

from screening_core.llm_client import (
    LLM_CONNECT_TIMEOUT_SECONDS,
    LLM_CV_READ_TIMEOUT_SECONDS,
    LLM_JD_READ_TIMEOUT_SECONDS,
    _os_trust_http_client,
    cv_llm_timeout,
    jd_llm_timeout,
)


# CV JSON needs the long wait (420s = measured 2026-10-22: 15-17 tok/s generations of
# 4-6K-token CV JSONs on the prod endpoint fit inside it with headroom). Job ads stay on
# the short wait. Connect fails fast either way.
def test_llm_timeouts_split_cv_and_jd() -> None:
    client = _os_trust_http_client()
    try:
        assert client.timeout is not None
        assert client.timeout.read == LLM_CV_READ_TIMEOUT_SECONDS == 420
        assert cv_llm_timeout().read == 420
        assert jd_llm_timeout().read == LLM_JD_READ_TIMEOUT_SECONDS == 60
        assert cv_llm_timeout().connect == LLM_CONNECT_TIMEOUT_SECONDS
        assert jd_llm_timeout().connect == LLM_CONNECT_TIMEOUT_SECONDS
    finally:
        client.close()
