import { v } from 'convex/values';
import { mutation, query } from './_generated/server';

export const generateUploadUrl = mutation({
  args: {},
  handler: async (ctx) => {
    return await ctx.storage.generateUploadUrl();
  },
});

export const create = mutation({
  args: {
    name: v.string(),
    type: v.union(v.literal('pdb'), v.literal('yaml'), v.literal('msa'), v.literal('db'), v.literal('other')),
    storageId: v.id('_storage'),
    size: v.number(),
    runId: v.union(v.id('runs'), v.null()),
  },
  handler: async (ctx, args) => {
    return await ctx.db.insert('files', {
      ...args,
      createdAt: Date.now(),
    });
  },
});

export const get = query({
  args: { id: v.id('files') },
  handler: async (ctx, args) => {
    return await ctx.db.get(args.id);
  },
});

export const getUrl = query({
  args: { id: v.id('files') },
  handler: async (ctx, args) => {
    const file = await ctx.db.get(args.id);
    if (!file) return null;
    return await ctx.storage.getUrl(file.storageId);
  },
});

export const listByRun = query({
  args: { runId: v.id('runs') },
  handler: async (ctx, args) => {
    return await ctx.db
      .query('files')
      .withIndex('by_run', (q) => q.eq('runId', args.runId))
      .collect();
  },
});

export const listByType = query({
  args: {
    type: v.union(v.literal('pdb'), v.literal('yaml'), v.literal('msa'), v.literal('db'), v.literal('other')),
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query('files')
      .withIndex('by_type', (q) => q.eq('type', args.type))
      .collect();
  },
});

export const remove = mutation({
  args: { id: v.id('files') },
  handler: async (ctx, args) => {
    const file = await ctx.db.get(args.id);
    if (file) {
      await ctx.storage.delete(file.storageId);
      await ctx.db.delete(args.id);
    }
  },
});
