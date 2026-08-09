import { Link } from 'next-transition-router';

export default function Navbar() {
  return (
    <nav className="fixed top-6 left-1/2 -translate-x-1/2 z-50 flex gap-6 bg-zinc-900 border border-white/10 rounded-full px-6 py-3">
      <Link href="/" className="text-white hover:text-emerald-400 transition-colors">Home</Link>
      <Link href="/dashboard" className="text-white hover:text-emerald-400 transition-colors">Dashboard</Link>
      <Link href="/upload" className="text-white hover:text-emerald-400 transition-colors">Data Ingestion</Link>
      <Link href="/network" className="text-white hover:text-emerald-400 transition-colors">Entity Graph</Link>
      <Link href="/reports" className="text-white hover:text-emerald-400 transition-colors">Sec 65B Reports</Link>
    </nav>
  );
}
