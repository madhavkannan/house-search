"use client";

import Image from "next/image";
import { useState } from "react";
import FavoriteButton from "./FavoriteButton";
import type { Listing } from "@/lib/supabase";

type Props = {
  listing: Listing;
  initialFavorited: boolean;
};

function formatPrice(price: number | null): string {
  if (!price) return "Price on request";
  return `S$${price.toLocaleString("en-SG")}`;
}

function ShelterTag({ status }: { status: Listing["shelter_status"] }) {
  if (status === "confirmed") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-tag-ok-bg text-tag-ok-text">
        <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
        </svg>
        Shelter confirmed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-tag-warn-bg text-tag-warn-text">
      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      Shelter unverified
    </span>
  );
}

export default function ListingCard({ listing, initialFavorited }: Props) {
  const [isFavorited, setIsFavorited] = useState(initialFavorited);
  const [imgError, setImgError] = useState(false);

  async function handleToggle(id: string, next: boolean) {
    setIsFavorited(next); // optimistic
    try {
      const method = next ? "POST" : "DELETE";
      const url = next
        ? "/api/favorites"
        : `/api/favorites?listing_id=${id}`;
      const opts: RequestInit = { method };
      if (next) {
        opts.headers = { "Content-Type": "application/json" };
        opts.body = JSON.stringify({ listing_id: id });
      }
      const res = await fetch(url, opts);
      if (!res.ok) throw new Error("Request failed");
    } catch {
      setIsFavorited(!next); // rollback on error
    }
  }

  const firstMrt = listing.nearby_mrt?.[0];
  const firstSchool = listing.nearby_schools?.[0];
  const hasBeds = listing.bedrooms != null;
  const hasBaths = listing.bathrooms != null;
  const hasSize = listing.size_sqft != null;

  return (
    <div
      className="rounded-xl overflow-hidden bg-bg-card border border-border flex flex-col transition-all duration-[180ms] hover:shadow-[0_4px_24px_rgba(0,0,0,0.08)] hover:-translate-y-0.5"
    >
      {/* Property image */}
      <div className="relative aspect-video bg-bg-subtle flex items-center justify-center">
        {listing.image_url && !imgError ? (
          <Image
            src={listing.image_url}
            alt={listing.project_name ?? "Property"}
            fill
            className="object-cover"
            onError={() => setImgError(true)}
            unoptimized
          />
        ) : (
          <span className="text-3xl select-none" style={{ color: "var(--text-muted)" }}>🏠</span>
        )}
      </div>

      {/* Card body */}
      <div className="p-5 flex flex-col flex-1 gap-3">
        {/* Price + name */}
        <div>
          <p className="font-mono font-semibold text-lg leading-tight" style={{ color: "var(--text-primary)" }}>
            {formatPrice(listing.price)}
          </p>
          <p className="text-sm font-medium mt-0.5" style={{ color: "var(--text-secondary)" }}>
            {listing.project_name ?? "Unknown"}{" "}
            {listing.district && (
              <span className="font-normal" style={{ color: "var(--text-muted)" }}>
                · {listing.district}
              </span>
            )}
          </p>
        </div>

        {/* Stats */}
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {hasBeds ? `${listing.bedrooms} bed` : "? bed"}
          {" · "}
          {hasBaths ? `${listing.bathrooms} bath` : "? bath"}
          {hasSize ? ` · ${listing.size_sqft!.toLocaleString()} sqft` : ""}
          {listing.tenure ? ` · ${listing.tenure}` : ""}
        </p>

        {/* Divider */}
        <hr style={{ borderColor: "var(--border)" }} />

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5">
          {firstMrt && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-bg-subtle" style={{ color: "var(--text-secondary)" }}>
              🚇 {firstMrt}
            </span>
          )}
          {!firstMrt && listing.geocode_ok && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs bg-tag-warn-bg text-tag-warn-text">
              No MRT within 640m
            </span>
          )}
          {firstSchool && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-bg-subtle" style={{ color: "var(--text-secondary)" }}>
              🏫 {firstSchool}
            </span>
          )}
          {!firstSchool && listing.geocode_ok && (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs bg-tag-warn-bg text-tag-warn-text">
              No school within 1km
            </span>
          )}
          {!listing.geocode_ok && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Location unverified
            </span>
          )}
          <ShelterTag status={listing.shelter_status} />
        </div>

        {/* Action row */}
        <div className="flex items-center justify-between mt-auto pt-1">
          <a
            href={listing.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs font-medium underline-offset-2 hover:underline"
            style={{ color: "var(--accent)" }}
          >
            View listing ↗
          </a>
          <FavoriteButton
            listingId={listing.id}
            isFavorited={isFavorited}
            onToggle={handleToggle}
          />
        </div>
      </div>
    </div>
  );
}
