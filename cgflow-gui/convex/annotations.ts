import { v } from 'convex/values';
import { mutation, query } from './_generated/server';

export const create = mutation({
  args: {
    moleculeId: v.id('molecules'),
    note: v.string(),
    starred: v.boolean(),
    tags: v.array(v.string()),
  },
  handler: async (ctx, args) => {
    const now = Date.now();
    return await ctx.db.insert('annotations', {
      ...args,
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const update = mutation({
  args: {
    id: v.id('annotations'),
    note: v.optional(v.string()),
    starred: v.optional(v.boolean()),
    tags: v.optional(v.array(v.string())),
  },
  handler: async (ctx, args) => {
    const { id, ...updates } = args;
    const existing = await ctx.db.get(id);
    if (!existing) {
      throw new Error('Annotation not found');
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

export const getByMolecule = query({
  args: { moleculeId: v.id('molecules') },
  handler: async (ctx, args) => {
    return await ctx.db
      .query('annotations')
      .withIndex('by_molecule', (q) => q.eq('moleculeId', args.moleculeId))
      .first();
  },
});

export const toggleStar = mutation({
  args: { moleculeId: v.id('molecules') },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query('annotations')
      .withIndex('by_molecule', (q) => q.eq('moleculeId', args.moleculeId))
      .first();

    if (existing) {
      await ctx.db.patch(existing._id, {
        starred: !existing.starred,
        updatedAt: Date.now(),
      });
      return existing._id;
    }

    // Create new annotation with star
    const now = Date.now();
    return await ctx.db.insert('annotations', {
      moleculeId: args.moleculeId,
      note: '',
      starred: true,
      tags: [],
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const addTag = mutation({
  args: {
    moleculeId: v.id('molecules'),
    tag: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query('annotations')
      .withIndex('by_molecule', (q) => q.eq('moleculeId', args.moleculeId))
      .first();

    if (existing) {
      const tags = existing.tags.includes(args.tag)
        ? existing.tags
        : [...existing.tags, args.tag];
      
      await ctx.db.patch(existing._id, {
        tags,
        updatedAt: Date.now(),
      });
      return existing._id;
    }

    // Create new annotation with tag
    const now = Date.now();
    return await ctx.db.insert('annotations', {
      moleculeId: args.moleculeId,
      note: '',
      starred: false,
      tags: [args.tag],
      createdAt: now,
      updatedAt: now,
    });
  },
});

export const removeTag = mutation({
  args: {
    moleculeId: v.id('molecules'),
    tag: v.string(),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query('annotations')
      .withIndex('by_molecule', (q) => q.eq('moleculeId', args.moleculeId))
      .first();

    if (existing) {
      const tags = existing.tags.filter((t) => t !== args.tag);
      await ctx.db.patch(existing._id, {
        tags,
        updatedAt: Date.now(),
      });
    }
  },
});

export const remove = mutation({
  args: { id: v.id('annotations') },
  handler: async (ctx, args) => {
    await ctx.db.delete(args.id);
  },
});
