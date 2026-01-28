import { createContext, useContext } from 'react';
import { useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';

// Context to track if Convex is available
export const ConvexAvailableContext = createContext<boolean>(false);

export function useConvexAvailable() {
  return useContext(ConvexAvailableContext);
}

/**
 * Hook to fetch runs from Convex, returns empty array if Convex is not available
 */
export function useConvexRuns() {
  const isAvailable = useConvexAvailable();
  
  // Only call useQuery if Convex is available
  // Using a trick: pass "skip" to prevent the query when not available
  const runs = useQuery(
    api.runs.list,
    isAvailable ? {} : 'skip'
  );
  
  return isAvailable ? runs : null;
}
