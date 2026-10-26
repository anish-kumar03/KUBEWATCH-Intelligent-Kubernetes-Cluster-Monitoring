import React from 'react';
import { Loader2 } from 'lucide-react';

interface LoadingStateProps {
  message?: string;
  height?: number | string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Loading live cluster data...',
  height = '200px',
}) => {
  return (
    <div className="loading-state" style={{ minHeight: height }}>
      <Loader2 className="loading-state__spinner" size={24} />
      <span className="loading-state__message">{message}</span>
    </div>
  );
};
