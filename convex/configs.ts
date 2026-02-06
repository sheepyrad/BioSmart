import { v } from 'convex/values';
import { mutation, query } from './_generated/server';

const configValidator = v.object({
  _id: v.id('configs'),
  _creationTime: v.number(),
  name: v.string(),
  resultDir: v.string(),
  envDir: v.string(),
  maxAtoms: v.number(),
  subsamplingRatio: v.number(),
  proteinPath: v.string(),
  center: v.union(v.array(v.number()), v.null()),
  refLigandPath: v.union(v.string(), v.null()),
  size: v.array(v.number()),
  numSteps: v.number(),
  numSamplingPerStep: v.number(),
  temperatureMin: v.number(),
  temperatureMax: v.number(),
  seed: v.number(),
  poseModel: v.string(),
  poseSteps: v.number(),
  samplingTau: v.number(),
  randomActionProb: v.number(),
  replayWarmupStep: v.number(),
  replayCapacity: v.number(),
  boltzBaseYaml: v.string(),
  boltzTargetResidues: v.array(v.string()),
  boltzMsaPath: v.union(v.string(), v.null()),
  boltzCacheDir: v.union(v.string(), v.null()),
  boltzUseMsaServer: v.boolean(),
  createdAt: v.number(),
  updatedAt: v.number(),
  lastUsedAt: v.union(v.number(), v.null()),
});

export const create = mutation({
  args: {
    name: v.string(),
    resultDir: v.string(),
    envDir: v.string(),
    maxAtoms: v.number(),
    subsamplingRatio: v.number(),
    proteinPath: v.string(),
    center: v.union(v.array(v.number()), v.null()),
    refLigandPath: v.union(v.string(), v.null()),
    size: v.array(v.number()),
    numSteps: v.number(),
    numSamplingPerStep: v.number(),
    temperatureMin: v.number(),
    temperatureMax: v.number(),
    seed: v.number(),
    poseModel: v.string(),
    poseSteps: v.number(),
    samplingTau: v.number(),
    randomActionProb: v.number(),
    replayWarmupStep: v.number(),
    replayCapacity: v.number(),
    boltzBaseYaml: v.string(),
    boltzTargetResidues: v.array(v.string()),
    boltzMsaPath: v.union(v.string(), v.null()),
    boltzCacheDir: v.union(v.string(), v.null()),
    boltzUseMsaServer: v.boolean(),
  },
  returns: v.id('configs'),
  handler: async (ctx, args) => {
    const now = Date.now();
    return await ctx.db.insert('configs', {
      ...args,
      createdAt: now,
      updatedAt: now,
      lastUsedAt: now,
    });
  },
});

export const update = mutation({
  args: {
    id: v.id('configs'),
    name: v.optional(v.string()),
    resultDir: v.optional(v.string()),
    envDir: v.optional(v.string()),
    maxAtoms: v.optional(v.number()),
    subsamplingRatio: v.optional(v.number()),
    proteinPath: v.optional(v.string()),
    center: v.optional(v.union(v.array(v.number()), v.null())),
    refLigandPath: v.optional(v.union(v.string(), v.null())),
    size: v.optional(v.array(v.number())),
    numSteps: v.optional(v.number()),
    numSamplingPerStep: v.optional(v.number()),
    temperatureMin: v.optional(v.number()),
    temperatureMax: v.optional(v.number()),
    seed: v.optional(v.number()),
    poseModel: v.optional(v.string()),
    poseSteps: v.optional(v.number()),
    samplingTau: v.optional(v.number()),
    randomActionProb: v.optional(v.number()),
    replayWarmupStep: v.optional(v.number()),
    replayCapacity: v.optional(v.number()),
    boltzBaseYaml: v.optional(v.string()),
    boltzTargetResidues: v.optional(v.array(v.string())),
    boltzMsaPath: v.optional(v.union(v.string(), v.null())),
    boltzCacheDir: v.optional(v.union(v.string(), v.null())),
    boltzUseMsaServer: v.optional(v.boolean()),
    lastUsedAt: v.optional(v.union(v.number(), v.null())),
  },
  returns: v.id('configs'),
  handler: async (ctx, args) => {
    const { id, ...updates } = args;
    const existing = await ctx.db.get(id);
    if (!existing) {
      throw new Error('Config not found');
    }
    
    const filteredUpdates = Object.fromEntries(
      Object.entries(updates).filter(([_, v]) => v !== undefined)
    );
    
    await ctx.db.patch(id, {
      ...filteredUpdates,
      updatedAt: Date.now(),
    });
    
    return id;
  },
});

export const get = query({
  args: { id: v.id('configs') },
  returns: v.union(configValidator, v.null()),
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

export const list = query({
  args: {},
  returns: v.array(configValidator),
  handler: async (ctx) => {
    return await ctx.db.query('configs').order('desc').collect();
  },
});

export const listByLastUsed = query({
  args: { limit: v.optional(v.number()) },
  returns: v.array(configValidator),
  handler: async (ctx, args) => {
    const limit = args.limit ?? 20;
    return await ctx.db
      .query('configs')
      .withIndex('by_last_used', (q) => q)
      .order('desc')
      .take(limit);
  },
});

export const getByName = query({
  args: { name: v.string() },
  returns: v.union(configValidator, v.null()),
  handler: async (ctx, args) => {
    return await ctx.db
      .query('configs')
      .withIndex('by_name', (q) => q.eq('name', args.name))
      .first();
  },
});

export const remove = mutation({
  args: { id: v.id('configs') },
  returns: v.null(),
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
    return null;
  },
});
