/** 运行页与配置页共用的 API 响应解析（FastAPI detail 数组 / 纯文本错误体） */
(function () {
  function formatApiDetail(detail) {
    if (detail == null || detail === "") return "";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === "string") return item;
          if (item && typeof item.msg === "string") {
            const loc = Array.isArray(item.loc)
              ? item.loc.filter((part) => part !== "body").join(" · ")
              : "";
            return loc ? `${loc}：${item.msg}` : item.msg;
          }
          try {
            return JSON.stringify(item);
          } catch {
            return String(item);
          }
        })
        .filter(Boolean)
        .join("；");
    }
    if (typeof detail === "object") {
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.msg === "string") return detail.msg;
      try {
        return JSON.stringify(detail);
      } catch {
        return String(detail);
      }
    }
    return String(detail);
  }

  function apiErrorMessage(data, fallback) {
    const text = formatApiDetail(data && data.detail);
    return text || fallback;
  }

  async function readFetchResponse(response) {
    const raw = await response.text();
    let data = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: raw.trim() };
      }
    }
    return { ok: response.ok, status: response.status, data, raw };
  }

  window.geniApi = {
    formatApiDetail,
    apiErrorMessage,
    readFetchResponse,
  };
})();
