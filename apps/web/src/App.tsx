import { Routes, Route, Link, Navigate } from "react-router-dom";
import { AudioLines } from "lucide-react";
import { HomePage } from "./pages/HomePage";
import { JoinRoomPage } from "./pages/JoinRoomPage";

function Brand() {
  return (
    <Link className="brand" to="/" aria-label="RoleCallAI home">
      <span className="brand-mark" aria-hidden="true"><AudioLines size={21} /></span>
      <span>RoleCall<span className="brand-accent">AI</span></span>
    </Link>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <Brand />
        <span className="phase-pill"><span className="status-dot" /> Phase 1 · voice only</span>
      </header>
      <main id="main-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/manage/:roomId" element={<Navigate to="/" replace />} />
          <Route path="/join/:roomId" element={<JoinRoomPage />} />
          <Route path="*" element={<div className="empty-state"><h1>That room isn’t here.</h1><Link className="button primary" to="/">Create a room</Link></div>} />
        </Routes>
      </main>
    </div>
  );
}
