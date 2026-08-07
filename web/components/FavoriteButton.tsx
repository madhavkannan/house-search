"use client";

import { useTransition } from "react";

type Props = {
  listingId: string;
  isFavorited: boolean;
  onToggle: (id: string, next: boolean) => Promise<void>;
};

export default function FavoriteButton({ listingId, isFavorited, onToggle }: Props) {
  const [isPending, startTransition] = useTransition();

  function handleClick() {
    startTransition(async () => {
      await onToggle(listingId, !isFavorited);
    });
  }

  return (
    <button
      onClick={handleClick}
      disabled={isPending}
      aria-label={isFavorited ? "Remove from saved" : "Save listing"}
      className={`
        w-8 h-8 rounded-full flex items-center justify-center
        transition-all duration-150
        ${isPending ? "opacity-50" : "hover:bg-bg-subtle"}
        ${isFavorited ? "text-accent" : "text-text-muted hover:text-text-secondary"}
      `}
    >
      {isFavorited ? (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
          <path d="M9.653 16.915l-.005-.003-.019-.01a20.759 20.759 0 01-1.162-.682 22.045 22.045 0 01-2.582-2.184C4.045 12.733 2 10.352 2 7.5a4.5 4.5 0 018-2.828A4.5 4.5 0 0118 7.5c0 2.852-2.044 5.233-3.885 6.536a22.049 22.049 0 01-3.744 2.051l-.019.01-.005.003h-.002a.739.739 0 01-.69.001l-.002-.001z" />
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-4 h-4">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12z" />
        </svg>
      )}
    </button>
  );
}
