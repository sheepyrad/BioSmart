import { v } from 'convex/values';
import { mutation, query } from './_generated/server';

const runValidator = v.object({
  _id: v.id('runs'),
  _creationTime: v.number(),
  configId: v.id('configs'),
  name: v.string(),
  status: v.union(
    v.literal('idle'),
    v.literal('running'),
    v.literal('paused'),
    v.literal('completed'),
    v.literal('error')
  ),
  currentStep: v.number(),
  totalSteps: v.number(),
  resultDir: v.string(),
  checkpointPath: v.union(v.string(), v.null()),
  error: v.union(v.string(), v.null()),
  startedAt: v.union(v.number(), v.null()),
  completedAt: v.union(v.number(), v.null()),
  lastUpdatedAt: v.number(),
});

export const create = mutation({
  args: {
    configId: v.id('configs'),
    name: v.string(),
    resultDir: v.string(),
    totalSteps: v.number(),
  },
  returns: v.id('runs'),
  handler: async (ctx, args) => {
    const now = Date.now();
    return await ctx.db.insert('runs', {
      configId: args.configId,
      name: args.name,
      status: 'idle',
      currentStep: 0,
      totalSteps: args.totalSteps,
      resultDir: args.resultDir,
      checkpointPath: null,
      error: null,
      startedAt: null,
      completedAt: null,
      lastUpdatedAt: now,
    });
  },
});

export const updateStatus = mutation({
  args: {
    id: v.id('runs'),
    status: v.union(
      v.literal('idle'),
      v.literal('running'),
      v.literal('paused'),
      v.literal('completed'),
      v.literal('error')
    ),
    currentStep: v.optional(v.number()),
    checkpointPath: v.optional(v.union(v.string(), v.null())),
    error: v.optional(v.union(v.string(), v.null())),
  },
  returns: v.id('runs'),
  handler: async (ctx, args) => {
    const { id, ...updates } = args;
    const existing = await ctx.db.get(id);
    if (!existing) {
      throw new Error('Run not found');
    }

    const now = Date.now();
    const patchData: Record<string, unknown> = {
      status: updates.status,
      lastUpdatedAt: now,
    };

    if (updates.currentStep !== undefined) {
      patchData.currentStep = updates.currentStep;
    }
    if (updates.checkpointPath !== undefined) {
      patchData.checkpointPath = updates.checkpointPath;
    }
    if (updates.error !== undefined) {
      patchData.error = updates.error;
    }

    // Set timestamps based on status
    if (updates.status === 'running' && existing.status !== 'running') {
      patchData.startedAt = now;
    }
    if (updates.status === 'completed' || updates.status === 'error') {
      patchData.completedAt = now;
    }

    await ctx.db.patch(id, patchData);
    return id;
  },
});

export const get = query({
  args: { id: v.id('runs') },
  returns: v.union(runValidator, v.null()),
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

export const list = query({
  args: {
    status: v.optional(
      v.union(
        v.literal('idle'),
        v.literal('running'),
        v.literal('paused'),
        v.literal('completed'),
        v.literal('error')
      )
    ),
  },
  returns: v.array(runValidator),
  handler: async (ctx, args) => {
    if (args.status) {
      return await ctx.db
        .query('runs')
        .withIndex('by_status', (q) => q.eq('status', args.status!))
        .order('desc')
        .collect();
    }
    return await ctx.db.query('runs').order('desc').collect();
  },
});

export const getByConfig = query({
  args: { configId: v.id('configs') },
  returns: v.array(runValidator),
  handler: async (ctx, args) => {
    return await ctx.db
      .query('runs')
      .withIndex('by_config', (q) => q.eq('configId', args.configId))
      .order('desc')
      .collect();
  },
});

export const remove = mutation({
  args: { id: v.id('runs') },
  returns: v.null(),
  handler: async (ctx, args) => {
    // Also delete associated molecules and files
    const molecules = await ctx.db
      .query('molecules')
      .withIndex('by_run', (q) => q.eq('runId', args.id))
      .collect();
    
    for (const mol of molecules) {
      // Delete annotations
      const annotations = await ctx.db
        .query('annotations')
        .withIndex('by_molecule', (q) => q.eq('moleculeId', mol._id))
        .collect();
      for (const ann of annotations) {
        await ctx.db.delete(ann._id);
      }
      await ctx.db.delete(mol._id);
    }

    // Delete associated files
    const files = await ctx.db
      .query('files')
      .withIndex('by_run', (q) => q.eq('runId', args.id))
      .collect();
    
    for (const file of files) {
      await ctx.storage.delete(file.storageId);
      await ctx.db.delete(file._id);
    }

    await ctx.db.delete(args.id);
    return null;
  },
});
