// js/app-common.js
(function () {
  const CATEGORIES = [
    { value: "all", label_en: "All categories", label_vi: "Tất cả danh mục" },
    { value: "air-fryer", label_en: "Air Fryer", label_vi: "Nồi chiên không dầu" },
    { value: "coffee", label_en: "Coffee", label_vi: "Máy pha cà phê" },
    { value: "blender", label_en: "Blender", label_vi: "Máy xay" },
    { value: "toaster", label_en: "Toaster", label_vi: "Máy nướng bánh" },
    { value: "microwave", label_en: "Microwave", label_vi: "Lò vi sóng" },
    { value: "rice-cooker", label_en: "Rice Cooker", label_vi: "Nồi cơm điện" },
    { value: "other", label_en: "Other", label_vi: "Khác" },
  ];

  const LANG_KEY = "dealhub_lang";

  function getLang() {
    const v = localStorage.getItem(LANG_KEY);
    return v === "vi" ? "vi" : "en";
  }
  function setLang(lang) {
    const v = lang === "vi" ? "vi" : "en";
    localStorage.setItem(LANG_KEY, v);
    return v;
  }

  function esc(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function fmtMoney(v) {
    return `$${Number(v || 0).toFixed(2)}`;
  }

  function slugify(str) {
    return String(str || "")
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function makeSlug(base) {
    const clean = slugify(base || "deal");
    const suffix = Date.now().toString(36).slice(-6);
    return `${clean}-${suffix}`;
  }

  function computeSavePercent(oldPrice, newPrice) {
    const oldP = Number(oldPrice || 0);
    const newP = Number(newPrice || 0);
    if (!oldP || newP >= oldP) return 0;
    return Math.round(((oldP - newP) / oldP) * 100);
  }

  function splitLines(text) {
    return String(text || "")
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  }

  function splitCSV(text) {
    return String(text || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
  }

  function categoryLabel(value, lang = "en") {
    const item = CATEGORIES.find((c) => c.value === value);
    if (!item) return value;
    return lang === "vi" ? item.label_vi : item.label_en;
  }

  function badgeLabel(b, lang = "en") {
    if (lang === "vi") {
      if (b === "flash") return "FLASH";
      if (b === "coupon") return "MÃ GIẢM";
      return "HOT";
    }
    if (b === "flash") return "FLASH";
    if (b === "coupon") return "COUPON";
    return "HOT";
  }

  function getTextByLang(deal, base, lang = "en") {
    const primary = deal?.[`${base}_${lang}`];
    const alt = deal?.[`${base}_${lang === "en" ? "vi" : "en"}`];
    const legacy = deal?.[base];
    return primary || alt || legacy || "";
  }

  function getArrayByLang(deal, base, lang = "en") {
    const primary = deal?.[`${base}_${lang}`];
    const alt = deal?.[`${base}_${lang === "en" ? "vi" : "en"}`];
    const legacy = deal?.[base];
    if (Array.isArray(primary) && primary.length) return primary;
    if (Array.isArray(alt) && alt.length) return alt;
    if (Array.isArray(legacy) && legacy.length) return legacy;
    return [];
  }

  function localizedDeal(deal, lang = "en") {
    return {
      ...deal,
      _lang: lang,
      title_t: getTextByLang(deal, "title", lang),
      short_desc_t: getTextByLang(deal, "short_desc", lang),
      description_t: getTextByLang(deal, "description", lang),
      highlights_t: getArrayByLang(deal, "highlights", lang),
      tags_t: getArrayByLang(deal, "tags", lang),
      seo_title_t: getTextByLang(deal, "seo_title", lang),
      seo_desc_t: getTextByLang(deal, "seo_desc", lang),
    };
  }

  async function getSession() {
    const { data, error } = await window.sb.auth.getSession();
    if (error) throw error;
    return data.session;
  }

  async function signIn(email, password) {
    const { data, error } = await window.sb.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
  }

  async function signOut() {
    const { error } = await window.sb.auth.signOut();
    if (error) throw error;
  }

  async function isAdmin() {
    const session = await getSession();
    return Boolean(session?.user?.email);
  }

  async function listPublicDeals({ limit = 50, orderBy = "created_at", asc = false } = {}) {
    const { data, error } = await window.sb
      .from("deals")
      .select("*")
      .eq("published", true)
      .order(orderBy, { ascending: asc })
      .limit(limit);
    if (error) throw error;
    return data || [];
  }

  async function listAdminDeals({ limit = 200 } = {}) {
    const { data, error } = await window.sb
      .from("deals")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);
    if (error) throw error;
    return data || [];
  }

  async function getPublicDealById(id) {
    const { data, error } = await window.sb
      .from("deals")
      .select("*")
      .eq("id", id)
      .eq("published", true)
      .single();
    if (error) throw error;
    return data;
  }

  async function getPublicDealBySlug(slug) {
    const { data, error } = await window.sb
      .from("deals")
      .select("*")
      .eq("slug", slug)
      .eq("published", true)
      .single();
    if (error) throw error;
    return data;
  }

  async function uploadImage(file, pathPrefix = "deal-images") {
    const fileName = `${Date.now()}-${file.name}`.replace(/\s+/g, "-");
    const filePath = `${pathPrefix}/${fileName}`;
    const { error } = await window.sb.storage.from("deal-images").upload(filePath, file, { upsert: true });
    if (error) throw error;
    const { data } = window.sb.storage.from("deal-images").getPublicUrl(filePath);
    return data?.publicUrl || null;
  }

  async function saveDeal(payload) {
    // upsert theo id (nếu có), nếu không thì insert
    if (payload?.id) {
      const { data, error } = await window.sb.from("deals").update(payload).eq("id", payload.id).select("*").single();
      if (error) throw error;
      return data;
    }
    const { data, error } = await window.sb.from("deals").insert(payload).select("*").single();
    if (error) throw error;
    return data;
  }

  async function deleteDeal(id) {
    const { error } = await window.sb.from("deals").delete().eq("id", id);
    if (error) throw error;
    return true;
  }

  function buildFacebookPost(deal, lang = "en") {
    const d = localizedDeal(deal, lang);
    const lines = [];
    lines.push(d.title_t || "Hot deal!");
    if (d.short_desc_t) lines.push(d.short_desc_t);
    if (deal?.affiliate_url) lines.push(deal.affiliate_url);
    return lines.join("\n");
  }

  async function copyText(text) {
    await navigator.clipboard.writeText(String(text || ""));
    return true;
  }

  async function trackDealClick({ dealId, slug, source = "web", lang = "en" }) {
    try {
      await window.sb.from("deal_clicks").insert({
        deal_id: dealId,
        slug,
        source,
        lang,
        page_path: location.pathname + location.search,
        referrer: document.referrer || null,
      });
    } catch (_) {}
  }

  async function trackDealView({ dealId, slug, source = "view", lang = "en" }) {
    // optional view tracking
    try {
      await window.sb.from("deal_clicks").insert({
        deal_id: dealId,
        slug,
        source,
        lang,
        page_path: location.pathname + location.search,
        referrer: document.referrer || null,
      });
    } catch (_) {}
  }

  async function listDealClicksRaw({ limit = 200 } = {}) {
    const { data, error } = await window.sb.from("deal_clicks").select("*").order("created_at", { ascending: false }).limit(limit);
    if (error) throw error;
    return data || [];
  }

  function getClientId() {
    const k = "dealhub_client_id";
    let v = localStorage.getItem(k);
    if (!v) {
      v = Math.random().toString(36).slice(2) + Date.now().toString(36).slice(2);
      localStorage.setItem(k, v);
    }
    return v;
  }

  function getUtmParams() {
    const p = new URLSearchParams(location.search);
    const obj = {};
    ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"].forEach((k) => {
      const v = p.get(k);
      if (v) obj[k] = v;
    });
    return obj;
  }

  function formatDateShort(value, lang = "en") {
    if (!value) return "";
    const d = new Date(value);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleString(lang === "vi" ? "vi-VN" : "en-US", {
      month: "short", day: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit"
    });
  }

  function isDealNew(deal) {
    if (deal?.promo_icon === "new") return true;
    const created = new Date(deal?.created_at || 0).getTime();
    if (!created) return false;
    return (Date.now() - created) <= 72 * 3600 * 1000; // 72h
  }

  function promoIconLabel(icon) {
    switch (icon) {
      case "new": return "NEW";
      case "fire": return "🔥 HOT";
      case "star": return "⭐ TOP";
      case "bolt": return "⚡ FLASH";
      case "gift": return "🎁";
      default: return "";
    }
  }

  async function reactToDeal({ dealId, vote }) {
    const clientId = getClientId();
    const v = vote === -1 ? -1 : 1;

    const { error: upsertErr } = await window.sb
      .from("deal_reactions")
      .upsert(
        { deal_id: dealId, client_id: clientId, vote: v },
        { onConflict: "deal_id,client_id" }
      );

    if (upsertErr) throw upsertErr;

    const { data, error } = await window.sb
      .from("deals")
      .select("id, like_count, dislike_count")
      .eq("id", dealId)
      .single();

    if (error) throw error;
    return data;
  }

  // ------------------------------------------------------
  // Alerts API (NEW) - gọi backend /api/alerts/subscribe
  // ------------------------------------------------------
  function looksLikeEmail(s) {
    const v = String(s || "").trim();
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v);
  }

  async function subscribeAlert({ email, keyword, category_id = null }) {
    const em = String(email || "").trim();
    const kw = String(keyword || "").trim();

    if (!looksLikeEmail(em)) {
      return { ok: false, message: "Invalid Email." };
    }
    if (!kw && !category_id) {
      return { ok: false, message: "Please enter both email and keyword." };
    }

    const res = await fetch("/api/alerts/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: em, keyword: kw, category_id }),
    });

    // backend trả JSON {ok, message, ...}
    const data = await res.json().catch(() => null);
    if (!data) return { ok: false, message: "Network error. Please try again." };
    return data;
  }

  window.DealApp = {
    CATEGORIES,
    getLang,
    setLang,
    esc,
    fmtMoney,
    slugify,
    makeSlug,
    badgeLabel,
    categoryLabel,
    computeSavePercent,
    splitLines,
    splitCSV,
    localizedDeal,
    getSession,
    signIn,
    signOut,
    isAdmin,
    listPublicDeals,
    listAdminDeals,
    getPublicDealById,
    getPublicDealBySlug,
    uploadImage,
    saveDeal,
    deleteDeal,
    buildFacebookPost,
    copyText,
    trackDealClick,
    listDealClicksRaw,
    getClientId,
    getUtmParams,
    formatDateShort,
    isDealNew,
    promoIconLabel,
    reactToDeal,
    trackDealView,

    // Alerts (NEW)
    subscribeAlert,
  };
})();