import { createClient } from "@supabase/supabase-js";
import ListingCard from "@/components/ListingCard";

async function getFavorites() {
  const supabase = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );

  const { data: favs } = await supabase
    .from("favorites")
    .select("listing_id, favorited_at")
    .order("favorited_at", { ascending: false });

  if (!favs || favs.length === 0) return { listings: [], favoritedIds: new Set<string>() };

  const ids = favs.map((f) => f.listing_id);
  const { data: listings } = await supabase
    .from("listings")
    .select("*")
    .in("id", ids);

  const favoritedIds = new Set(ids);
  return { listings: listings ?? [], favoritedIds };
}

export default async function FavoritesPage() {
  const { listings, favoritedIds } = await getFavorites();

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}>
          Saved
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
          {listings.length === 0
            ? "Nothing saved yet"
            : `${listings.length} saved listing${listings.length === 1 ? "" : "s"}`}
        </p>
      </div>

      {listings.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-32 text-center">
          <p className="text-4xl mb-4">♡</p>
          <p className="font-medium" style={{ color: "var(--text-primary)" }}>
            No saved listings
          </p>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            Tap the heart on any listing to save it here
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {listings.map((listing) => (
            <ListingCard
              key={listing.id}
              listing={listing}
              initialFavorited={favoritedIds.has(listing.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
