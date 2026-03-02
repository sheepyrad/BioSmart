import { v } from 'convex/values';
import { mutation, query } from './_generated/server';

// Field type validator - matches schema
const fieldTypeValidator = v.union(
  v.literal('protein_pdb'),
  v.literal('boltz_yaml'),
  v.literal('msa'),
  v.literal('other')
);

// File type validator
const fileTypeValidator = v.union(
  v.literal('pdb'),
  v.literal('yaml'),
  v.literal('msa'),
  v.literal('db'),
  v.literal('other')
);

export const generateUploadUrl = mutation({
  args: {},
  handler: async (ctx) => {
    return await ctx.storage.generateUploadUrl();
  },
});

export const create = mutation({
  args: {
    name: v.string(),
    type: fileTypeValidator,
    fieldType: fieldTypeValidator,
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

// Get file URL by storage ID directly
export const getUrlByStorageId = query({
  args: { storageId: v.id('_storage') },
  handler: async (ctx, args) => {
    return await ctx.storage.getUrl(args.storageId);
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
    type: fileTypeValidator,
  },
  handler: async (ctx, args) => {
    return await ctx.db
      .query('files')
      .withIndex('by_type', (q) => q.eq('type', args.type))
      .collect();
  },
});

// List files by field type (e.g., protein_pdb, boltz_yaml, msa) with URLs
export const listByFieldType = query({
  args: {
    fieldType: fieldTypeValidator,
  },
  handler: async (ctx, args) => {
    const files = await ctx.db
      .query('files')
      .withIndex('by_field_type', (q) => q.eq('fieldType', args.fieldType))
      .order('desc')
      .collect();
    
    // Include download URLs for each file
    return Promise.all(
      files.map(async (file) => ({
        ...file,
        url: await ctx.storage.getUrl(file.storageId),
      }))
    );
  },
});

// List all uploaded files (for browsing) with URLs
export const listAll = query({
  args: {},
  handler: async (ctx) => {
    const files = await ctx.db
      .query('files')
      .order('desc')
      .collect();
    
    // Include download URLs for each file
    return Promise.all(
      files.map(async (file) => ({
        ...file,
        url: await ctx.storage.getUrl(file.storageId),
      }))
    );
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
