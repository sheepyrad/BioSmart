import { useMutation, useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api';
import { useConvexAvailable } from './useConvex';
import type { Id } from '../../convex/_generated/dataModel';
import type { ConvexConfigInput, ConvexConfig } from '@/lib/configMapping';

export function useConvexConfigs(limit = 10) {
  const isAvailable = useConvexAvailable();

  const configs = useQuery(
    api.configs.listByLastUsed,
    isAvailable ? { limit } : 'skip'
  ) as ConvexConfig[] | undefined;

  const createConfig = useMutation(api.configs.create);
  const updateConfig = useMutation(api.configs.update);

  return {
    isAvailable,
    configs: isAvailable ? configs ?? null : null,
    createConfig: async (input: ConvexConfigInput) => {
      if (!isAvailable) return null;
      return (await createConfig(input)) as Id<'configs'>;
    },
    updateConfig: async (id: Id<'configs'>, updates: Partial<ConvexConfigInput> & { lastUsedAt?: number | null }) => {
      if (!isAvailable) return null;
      return (await updateConfig({ id, ...updates })) as Id<'configs'>;
    },
  };
}
