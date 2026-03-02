// js/supabase-config.js
window.SUPABASE_URL = "https://taxkfglkinkmuoyudrvz.supabase.co";

// Dùng Publishable Key (khuyên dùng) hoặc Anon Key đều được
window.SUPABASE_KEY = "sb_publishable_uNOOnw-VDKC6ZZSiL-v1JQ_jxqhC2B0";

window.sb = window.supabase.createClient(
  window.SUPABASE_URL,
  window.SUPABASE_KEY,
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  }
);