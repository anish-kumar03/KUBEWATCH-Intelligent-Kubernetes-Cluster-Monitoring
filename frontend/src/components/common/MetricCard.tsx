import React from 'react';
import type { LucideIcon } from 'lucide-react';

interface MetricCardProps {
  title: string;
  value: string | number | null | undefined;
  unit?: string;
  subtitle?: string;
  icon?: LucideIcon;
  badge?: React.ReactNode;
  isUnavailable?: boolean;
  unavailableReason?: string;
  trend?: {
    value: string;
    isPositive?: boolean;
  };
}

export const MetricCard: React.FC<MetricCardProps> = ({
  title,
  value,
  unit,
  subtitle,
  icon: Icon,
  badge,
  isUnavailable = false,
  unavailableReason = 'Metric not reporting',
  trend,
}) => {
  const isNullOrUndefined = value === null || value === undefined || isUnavailable;

  return (
    <div className={`metric-card ${isNullOrUndefined ? 'metric-card--unavailable' : ''}`}>
      <div className="metric-card__header">
        <div className="metric-card__title-group">
          {Icon && (
            <span className="metric-card__icon">
              <Icon size={16} />
            </span>
          )}
          <span className="metric-card__title">{title}</span>
        </div>
        {badge && <div className="metric-card__badge">{badge}</div>}
      </div>

      <div className="metric-card__body">
        {isNullOrUndefined ? (
          <div className="metric-card__unavailable-block">
            <span className="metric-card__unavailable-label">Unavailable</span>
            <span className="metric-card__unavailable-hint">{unavailableReason}</span>
          </div>
        ) : (
          <div className="metric-card__value-row">
            <span className="metric-card__value">{value}</span>
            {unit && <span className="metric-card__unit">{unit}</span>}
          </div>
        )}
      </div>

      {(subtitle || trend) && (
        <div className="metric-card__footer">
          {trend && (
            <span
              className={`metric-card__trend ${
                trend.isPositive ? 'metric-card__trend--positive' : 'metric-card__trend--negative'
              }`}
            >
              {trend.value}
            </span>
          )}
          {subtitle && <span className="metric-card__subtitle">{subtitle}</span>}
        </div>
      )}
    </div>
  );
};
