import React from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  height?: number | string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Data Fetch Failed',
  message = 'An unexpected error occurred while communicating with the cluster API.',
  onRetry,
  height = '180px',
}) => {
  return (
    <div className="error-state" style={{ minHeight: height }}>
      <div className="error-state__icon">
        <AlertTriangle size={24} />
      </div>
      <div className="error-state__content">
        <h4 className="error-state__title">{title}</h4>
        <p className="error-state__message">{message}</p>
        {onRetry && (
          <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
            <RefreshCw size={14} className="icon-mr" />
            Retry Request
          </button>
        )}
      </div>
    </div>
  );
};
