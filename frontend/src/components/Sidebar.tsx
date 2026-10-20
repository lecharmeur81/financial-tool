"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isActive, navGroups } from "@/lib/navigation";

export function Sidebar() {
  const pathname = usePathname() ?? "/";
  return (
    <nav className="sidebar" aria-label="Main navigation">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          CFI
        </span>
        <span className="brand-name">Capital Flow Intelligence</span>
      </div>
      {navGroups().map(({ group, items }) => (
        <div className="nav-group" key={group}>
          <p className="nav-group-label" id={`nav-group-${group.toLowerCase().replace(/ /g, "-")}`}>
            {group}
          </p>
          <ul aria-labelledby={`nav-group-${group.toLowerCase().replace(/ /g, "-")}`}>
            {items.map((item) => {
              const active = isActive(item.href, pathname);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={active ? "nav-link active" : "nav-link"}
                    aria-current={active ? "page" : undefined}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <p className="sidebar-footnote">Decision support — not financial advice.</p>
    </nav>
  );
}
