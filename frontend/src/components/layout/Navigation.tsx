import React from 'react';
import { LayoutDashboard, Boxes, LineChart, AlertTriangle, Lightbulb } from 'lucide-react';

export type TabId = 'overview' | 'workloads' | 'performance' | 'incidents' | 'recommendations';

interface NavigationProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  incidentsCount?: number | null;
}

interface NavItem {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  badge?: string | number | null;
}

export const Navigation: React.FC<NavigationProps> = ({
  activeTab,
  onTabChange,
  incidentsCount,
}) => {
  const items: NavItem[] = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard },
    { id: 'workloads', label: 'Workloads', icon: Boxes },
    { id: 'performance', label: 'Performance', icon: LineChart },
    {
      id: 'incidents',
      label: 'Incidents',
      icon: AlertTriangle,
      badge: incidentsCount !== null && incidentsCount !== undefined ? incidentsCount : undefined,
    },
    { id: 'recommendations', label: 'Recommendations', icon: Lightbulb },
  ];

  return (
    <nav className="app-nav" aria-label="Dashboard views">
      <ul className="app-nav__list" role="tablist">
        {items.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;

          return (
            <li key={item.id} className="app-nav__item" role="presentation">
              <button
                type="button"
                role="tab"
                id={`tab-${item.id}`}
                aria-selected={isActive}
                aria-controls={`panel-${item.id}`}
                className={`app-nav__button ${isActive ? 'app-nav__button--active' : ''}`}
                onClick={() => onTabChange(item.id)}
              >
                <Icon size={16} className="app-nav__icon" />
                <span className="app-nav__label">{item.label}</span>
                {item.badge !== undefined && (
                  <span className="app-nav__badge">{item.badge}</span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};
