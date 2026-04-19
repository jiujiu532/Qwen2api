export function getAuthHeader() {
  const key = localStorage.getItem('qwen2api_key') || 'admin';
  return { Authorization: `Bearer ${key}` };
}
