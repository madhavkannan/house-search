import { createClient } from "@supabase/supabase-js";
import LoadMore from "@/components/LoadMore";

const PAGE_SIZE = 20;

async function getListings() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  const [listingsResult, favoritesResult] = await Promise.all([
    supabase
      .from("listings")
      .select("*", { count: "exact" })
      .order("first_seen_at", { ascending: false })
      .range(0, PAGE_SIZE - 1),
    supabase.from("favorites").select("listing_id"),
  ]);

  return {
    listings: listingsResult.data ?? [],
    total: listingsResult.count ?? 0,
    favoritedIds: new Set((favoritesResult.data ?? []).map((f) => f.listing_id)),
  };
}

export default async function HomePage() {
  const { listings, total, favoritedIds } = await getListings();

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
          New listings
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          {total === 0
            ? "No listings yet — the screener runs at 9am and 9pm SGT"
            : `${total.toLocaleString()} condo${total === 1 ? "" : "s"} matching your criteria · D2, D9, D11, D14–D16 · ≤S$3.2M · 3BR · ≥1,200 sqft`}
        </p>
      </div>

      {listings.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-32 text-center">
          <p className="text-4xl mb-4">🏠</p>
          <p className="font-medium" style={{ color: "var(--text-primary)" }}>
            No listings yet
          </p>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            The screener runs automatically at 9am and 9pm SGT
          </p>
        </div>
      ) : (
        <LoadMore
          initialListings={listings}
          favoritedIds={favoritedIds}
          total={total}
        />
      )}
    </div>
  );
}
