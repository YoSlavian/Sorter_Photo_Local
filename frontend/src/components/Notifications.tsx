import { useStudio } from '../state/store';

/** Transient feedback. Errors stay until dismissed; everything else expires. */
export function Notifications() {
  const notices = useStudio((state) => state.notices);
  const dismiss = useStudio((state) => state.dismiss);
  if (!notices.length) return null;

  return (
    <div className="ba-notices" role="status" aria-live="polite">
      {notices.map((notice) => (
        <div key={notice.id} className={`ba-notice ba-notice--${notice.kind}`}>
          <span style={{ flex: 1 }}>{notice.message}</span>
          <button
            type="button"
            className="ba-notice__close"
            onClick={() => dismiss(notice.id)}
            aria-label="Закрыть"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
