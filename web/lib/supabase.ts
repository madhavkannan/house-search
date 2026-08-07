import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export type Listing = {
  id: string;
  source: string;
  source_id: string;
  url: string;
  project_name: string | null;
  address: string | null;
  district: string | null;
  price: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  size_sqft: number | null;
  tenure: string | null;
  image_url: string | null;
  shelter_status: "confirmed" | "unverified" | "absent";
  nearby_schools: string[] | null;
  nearby_mrt: string[] | null;
  geocode_ok: boolean;
  first_seen_at: string;
};

export type Favorite = {
  listing_id: string;
  favorited_at: string;
};
