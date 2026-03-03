// js/supabase-config.js
window.SUPABASE_URL = "https://taxkfglkinkmuoyudrvz.supabase.co";
window.SUPABASE_KEY = "sb_publishable_uNOOnw-VDKC6ZZSiL-v1JQ_jxqhC2B0";

// supabase-js CDN v2 thường expose global là `supabase`
const supa = window.supabase || supabase;

window.sb = supa.createClient(window.SUPABASE_URL, window.SUPABASE_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});