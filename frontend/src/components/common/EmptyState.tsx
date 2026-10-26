import React from 'react';
import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
  height?: number | string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon = Inbox,
  title,
  description,
  action,
  height = '200px',
}) => {
  return (
    <div className="empty-state" style={{ minHeight: height }}>
      <div className="empty-state__icon">
        <Icon size={28} />
      </div>
      <h4 className="empty-state__title">{title}</h4>
      <p className="empty-state__description">{description}</p>
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
};
