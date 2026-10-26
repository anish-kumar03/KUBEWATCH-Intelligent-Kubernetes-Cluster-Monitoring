import React from 'react';

export type StatusVariant = 'success' | 'warning' | 'error' | 'info' | 'neutral';

interface StatusBadgeProps {
  status: string;
  variant?: StatusVariant;
  size?: 'sm' | 'md';
}

function resolveVariant(status: string): StatusVariant {
  const s = status.toLowerCase();
  if (['ready', 'running', 'healthy', 'true', 'active', 'ok', 'available'].includes(s)) {
    return 'success';
  }
  if (['pending', 'waiting', 'degraded', 'warning'].includes(s)) {
    return 'warning';
  }
  if (['failed', 'error', 'notready', 'not ready', 'critical', 'unavailable'].includes(s)) {
    return 'error';
  }
  if (['succeeded', 'completed', 'info'].includes(s)) {
    return 'info';
  }
  return 'neutral';
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, variant, size = 'sm' }) => {
  const effectiveVariant = variant || resolveVariant(status);

  return (
    <span className={`status-badge status-badge--${effectiveVariant} status-badge--${size}`}>
      <span className="status-badge__dot" />
      <span className="status-badge__label">{status}</span>
    </span>
  );
};
