"use client";

import { useState, useTransition } from "react";
import ListingCard from "./ListingCard";
import type { Listing } from "@/lib/supabase";

type Props = {
  initialListings: Listing[];
  favoritedIds: Set<string>;
  total: number;
};

const PAGE_SIZE = 20;

export default function LoadMore({ initialListings, favoritedIds, total }: Props) {
  const [listings, setListings] = useState<Listing[]>(initialListings);
  const [page, setPage] = useState(1);
  const [isPending, startTransition] = useTransition();

  const hasMore = listings.length < total;

  function loadMore() {
    startTransition(async () => {
      const nextPage = page + 1;
      const res = await fetch(`/api/listings?page=${nextPage}&limit=${PAGE_SIZE}`);
      const data = await res.json();
      setListings((prev) => [...prev, ...(data.listings ?? [])]);
      setPage(nextPage);
    });
  }

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {listings.map((listing) => (
          <ListingCard
            key={listing.id}
            listing={listing}
            initialFavorited={favoritedIds.has(listing.id)}
          />
        ))}
      </div>

      {hasMore && (
        <button
          onClick={loadMore}
          disabled={isPending}
          className="mt-8 w-full py-3 text-sm font-medium rounded-lg border transition-colors disabled:opacity-50"
          style={{
            borderColor: "var(--border)",
            color: "var(--text-secondary)",
            backgroundColor: "transparent",
          }}
          onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "var(--bg-subtle)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
        >
          {isPending ? "Loading…" : `Load more (${total - listings.length} remaining)`}
        </button>
      )}
    </>
  );
}
