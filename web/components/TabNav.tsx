"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

export default function TabNav() {
  const pathname = usePathname();
  const [favCount, setFavCount] = useState<number>(0);

  useEffect(() => {
    async function fetchCount() {
      const { count } = await supabase
        .from("favorites")
        .select("*", { count: "exact", head: true });
      setFavCount(count ?? 0);
    }
    fetchCount();
  }, []);

  const isHome = pathname === "/";
  const isFavs = pathname === "/favorites";

  const tabClass = (active: boolean) =>
    `text-sm font-medium tracking-wide transition-colors px-1 pb-0.5 ${
      active
        ? "text-white border-b border-accent"
        : "text-text-muted hover:text-white/80"
    }`;

  return (
    <nav
      className="sticky top-0 z-30 w-full flex items-center justify-between px-6 lg:px-12"
      style={{ backgroundColor: "var(--bg-dark)", height: "56px" }}
    >
      <Link
        href="/"
        className="text-white font-medium text-sm tracking-tight"
        style={{ letterSpacing: "-0.01em" }}
      >
        house search
      </Link>

      <div className="flex items-center gap-6">
        <Link href="/" className={tabClass(isHome)}>
          Home
        </Link>
        <Link href="/favorites" className={tabClass(isFavs)}>
          Saved
          {favCount > 0 && (
            <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-semibold bg-accent text-white">
              {favCount > 99 ? "99+" : favCount}
            </span>
          )}
        </Link>
      </div>
    </nav>
  );
}
