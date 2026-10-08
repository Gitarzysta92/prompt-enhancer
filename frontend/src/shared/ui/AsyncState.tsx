import { Icon } from "./Icon";

export function LoadingState({ label }: { label: string }) {
  return (
    <div aria-atomic="true" aria-live="polite" className="async-state" role="status">
      <span aria-hidden="true" className="spinner" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  title = "Something needs attention",
  actionLabel = "Try again",
}: {
  message: string;
  onRetry?: () => void;
  title?: string;
  actionLabel?: string;
}) {
  return (
    <div className="async-state async-state--error" role="alert">
      <span className="async-state__icon">
        <Icon name="x" />
      </span>
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
      </div>
      {onRetry && (
        <button className="button button--secondary" onClick={onRetry} type="button">
          {actionLabel}
        </button>
      )}
    </div>
  );
}
