// পেজ লোড হওয়ার সময় স্কেলিটন (হঠাৎ ফাঁকা বা লাফানো পেজ এড়াতে)
export default function Loading() {
  return (
    <div aria-busy="true" aria-label="লোড হচ্ছে">
      <div className="sk sk-title" />
      <div className="sk sk-line" style={{ width: "100%", height: 44 }} />
      <div className="sk sk-line" style={{ width: "100%", height: 44 }} />
      <div style={{ height: 8 }} />
      {[0, 1, 2, 3].map((i) => <div key={i} className="sk sk-card" />)}
    </div>
  );
}
