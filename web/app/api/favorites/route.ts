import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
);

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { listing_id } = body;

  if (!listing_id) {
    return NextResponse.json({ error: "listing_id required" }, { status: 400 });
  }

  const { error } = await supabase
    .from("favorites")
    .insert({ listing_id })
    .select();

  if (error && error.code !== "23505") { // ignore duplicate
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const { count } = await supabase
    .from("favorites")
    .select("*", { count: "exact", head: true });

  return NextResponse.json({ ok: true, count: count ?? 0 });
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const listing_id = searchParams.get("listing_id");

  if (!listing_id) {
    return NextResponse.json({ error: "listing_id required" }, { status: 400 });
  }

  const { error } = await supabase
    .from("favorites")
    .delete()
    .eq("listing_id", listing_id);

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const { count } = await supabase
    .from("favorites")
    .select("*", { count: "exact", head: true });

  return NextResponse.json({ ok: true, count: count ?? 0 });
}
