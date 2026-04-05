(function () {
  const PREFIX = "ui-cache:v1:";

  function storage() {
    try {
      return window.localStorage;
    } catch (_) {
      return null;
    }
  }

  function buildKey(key) {
    return `${PREFIX}${String(key || "")}`;
  }

  function read(key) {
    const ls = storage();
    if (!ls) return null;
    try {
      const raw = ls.getItem(buildKey(key));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      if (!Object.prototype.hasOwnProperty.call(parsed, "savedAt")) return null;
      if (!Object.prototype.hasOwnProperty.call(parsed, "data")) return null;
      return parsed;
    } catch (_) {
      return null;
    }
  }

  function write(key, data) {
    const ls = storage();
    if (!ls) return;
    const payload = {
      savedAt: Date.now(),
      data,
    };
    try {
      ls.setItem(buildKey(key), JSON.stringify(payload));
    } catch (_) {
      // Ignore quota/storage errors on UI cache layer.
    }
  }

  function invalidate(key) {
    const ls = storage();
    if (!ls) return;
    try {
      ls.removeItem(buildKey(key));
    } catch (_) {
      // noop
    }
  }

  function invalidatePrefix(prefix) {
    const ls = storage();
    if (!ls) return;
    const fullPrefix = buildKey(prefix || "");
    const keys = [];
    try {
      for (let i = 0; i < ls.length; i += 1) {
        const key = ls.key(i);
        if (key && key.startsWith(fullPrefix)) {
          keys.push(key);
        }
      }
      keys.forEach((key) => ls.removeItem(key));
    } catch (_) {
      // noop
    }
  }

  async function parseError(res) {
    try {
      const text = await res.text();
      return text || `HTTP ${res.status}`;
    } catch (_) {
      return `HTTP ${res.status}`;
    }
  }

  async function fetchJson(url, options = {}) {
    const cacheKey = options.key || String(url || "");
    const ttlMs = Math.max(0, Number(options.ttlMs || 0));
    const staleOnError = options.staleOnError !== false;
    const bypassCache = Boolean(options.bypassCache);
    const cached = bypassCache ? null : read(cacheKey);
    const ageMs = cached ? Date.now() - Number(cached.savedAt || 0) : Number.POSITIVE_INFINITY;

    if (cached && ttlMs > 0 && ageMs <= ttlMs) {
      return {
        data: cached.data,
        fromCache: true,
        stale: false,
        ageMs,
      };
    }

    try {
      const res = await fetch(url, options.fetchOptions || undefined);
      if (!res.ok) {
        throw new Error(await parseError(res));
      }
      const data = await res.json();
      write(cacheKey, data);
      return {
        data,
        fromCache: false,
        stale: false,
        ageMs: 0,
      };
    } catch (error) {
      if (cached && staleOnError) {
        return {
          data: cached.data,
          fromCache: true,
          stale: true,
          ageMs,
          error,
        };
      }
      throw error;
    }
  }

  window.UiCache = {
    fetchJson,
    read,
    write,
    invalidate,
    invalidatePrefix,
  };
})();
