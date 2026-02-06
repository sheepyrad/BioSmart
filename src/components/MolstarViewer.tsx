import { useEffect, useRef, useState } from 'react';
import { createPluginUI } from 'molstar/lib/mol-plugin-ui';
import { renderReact18 } from 'molstar/lib/mol-plugin-ui/react18';
import { PluginUIContext } from 'molstar/lib/mol-plugin-ui/context';
import { StructureSelection, QueryContext, Structure, StructureProperties, StructureElement } from 'molstar/lib/mol-model/structure';
import { OrderedSet } from 'molstar/lib/mol-data/int';
import { MolScriptBuilder as MS } from 'molstar/lib/mol-script/language/builder';
import { compile } from 'molstar/lib/mol-script/runtime/query/compiler';
import { InteractivityManager } from 'molstar/lib/mol-plugin-state/manager/interactivity';

// Import Mol* pre-built styles
import 'molstar/build/viewer/molstar.css';

interface MolstarViewerProps {
  pdbContent: string | null;
  selectedResidues: string[];
  onResidueSelect: (residues: string[]) => void;
  /** If true, clicking always toggles. If false, requires Ctrl/Cmd for multi-select */
  multiSelectMode?: boolean;
}

export default function MolstarViewer({
  pdbContent,
  selectedResidues,
  onResidueSelect,
  multiSelectMode = true, // Default to always toggle (multi-select)
}: MolstarViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const pluginRef = useRef<PluginUIContext | null>(null);
  const selectedResiduesRef = useRef<string[]>(selectedResidues);
  const onResidueSelectRef = useRef(onResidueSelect);
  const multiSelectModeRef = useRef(multiSelectMode);
  const [isInitialized, setIsInitialized] = useState(false);

  // Keep refs in sync with props
  useEffect(() => {
    selectedResiduesRef.current = selectedResidues;
  }, [selectedResidues]);

  useEffect(() => {
    onResidueSelectRef.current = onResidueSelect;
  }, [onResidueSelect]);

  useEffect(() => {
    multiSelectModeRef.current = multiSelectMode;
  }, [multiSelectMode]);

  // Initialize Mol* plugin
  useEffect(() => {
    if (!containerRef.current || pluginRef.current) return;

    async function init() {
      try {
        const plugin = await createPluginUI({
          target: containerRef.current!,
          render: renderReact18,
        });

        // Subscribe to click events for residue selection
        plugin.behaviors.interaction.click.subscribe((event: InteractivityManager.ClickEvent) => {
          const { current, modifiers } = event;
          
          if (!current || current.loci.kind !== 'element-loci') return;
          
          const loci = current.loci;
          if (loci.elements.length === 0) return;

          const clickedResidues: string[] = [];
          
          // Extract residue info from clicked element
          for (const element of loci.elements) {
            const { unit, indices } = element;
            
            // Get the first index from the OrderedSet
            const firstIdx = OrderedSet.getAt(indices, 0);
            if (firstIdx === undefined) continue;
            
            // Create a proper location for property access
            const loc = StructureElement.Location.create(loci.structure, unit, unit.elements[firstIdx]);
            
            try {
              const chainId = StructureProperties.chain.auth_asym_id(loc);
              const seqId = StructureProperties.residue.auth_seq_id(loc);
              
              const resId = `${chainId}:${seqId}`;
              if (!clickedResidues.includes(resId)) {
                clickedResidues.push(resId);
              }
            } catch (err) {
              console.warn('Could not extract residue info:', err);
            }
          }

          if (clickedResidues.length > 0) {
            const currentSelection = selectedResiduesRef.current;
            const isMultiSelect = multiSelectModeRef.current || modifiers?.control || modifiers?.meta;
            
            let newSelection: string[];
            
            if (isMultiSelect) {
              // Multi-select mode: toggle clicked residues
              newSelection = [...currentSelection];
              for (const resId of clickedResidues) {
                const idx = newSelection.indexOf(resId);
                if (idx >= 0) {
                  newSelection.splice(idx, 1);
                } else {
                  newSelection.push(resId);
                }
              }
            } else {
              // Single-select mode: replace selection with clicked residue
              const resId = clickedResidues[0]!;
              const alreadySelected = currentSelection.includes(resId) && currentSelection.length === 1;
              newSelection = alreadySelected ? [] : [resId];
            }
            
            onResidueSelectRef.current(newSelection);
          }
        });

        pluginRef.current = plugin;
        setIsInitialized(true);
      } catch (err) {
        console.error('Failed to initialize Mol* plugin:', err);
      }
    }

    init();

    return () => {
      pluginRef.current?.dispose();
      pluginRef.current = null;
    };
  }, []);

  // Load structure when pdbContent changes
  useEffect(() => {
    if (!pluginRef.current || !pdbContent || !isInitialized) return;

    const loadStructure = async () => {
      const plugin = pluginRef.current!;
      
      try {
        // Clear existing structures
        await plugin.clear();

        // Load PDB data from string
        const data = await plugin.builders.data.rawData({
          data: pdbContent,
          label: 'structure',
        });

        const trimmed = pdbContent.trim();
        const format = trimmed.startsWith('data_') || trimmed.includes('loop_') ? 'mmcif' : 'pdb';
        const trajectory = await plugin.builders.structure.parseTrajectory(data, format as any);
        await plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default');

        // Reset camera to fit structure
        plugin.canvas3d?.requestCameraReset();
      } catch (err) {
        console.error('Failed to load structure:', err);
      }
    };

    loadStructure();
  }, [pdbContent, isInitialized]);

  // Highlight selected residues
  useEffect(() => {
    if (!pluginRef.current || !isInitialized) return;
    
    const plugin = pluginRef.current;
    
    // Clear existing selections
    plugin.managers.interactivity.lociSelects.deselectAll();
    
    if (selectedResidues.length === 0) {
      plugin.managers.interactivity.lociHighlights.clearHighlights();
      return;
    }

    const highlightResidues = async () => {
      try {
        // Get the current structure
        const structures = plugin.managers.structure.hierarchy.current.structures;
        if (structures.length === 0) return;
        
        const structureRef = structures[0];
        if (!structureRef?.cell?.obj?.data) return;
        
        const structure = structureRef.cell.obj.data as Structure;

        // Build selection expression for all selected residues
        const groups = selectedResidues.map((resId) => {
          const [chain, seqStr] = resId.split(':');
          const seq = parseInt(seqStr!, 10);
          
          return MS.struct.generator.atomGroups({
            'chain-test': MS.core.rel.eq([
              MS.struct.atomProperty.macromolecular.auth_asym_id(),
              chain!,
            ]),
            'residue-test': MS.core.rel.eq([
              MS.struct.atomProperty.macromolecular.auth_seq_id(),
              seq,
            ]),
          });
        });

        const expression = MS.struct.combinator.merge(groups);
        const query = compile<StructureSelection>(expression);
        const selection = query(new QueryContext(structure));
        const loci = StructureSelection.toLociWithSourceUnits(selection);

        // Highlight and select the residues
        plugin.managers.interactivity.lociHighlights.highlightOnly({ loci });
        plugin.managers.interactivity.lociSelects.select({ loci });
        
        // Focus camera on selection
        plugin.managers.camera.focusLoci(loci);
      } catch (err) {
        console.error('Failed to highlight residues:', err);
      }
    };

    highlightResidues();
  }, [selectedResidues, isInitialized]);

  if (!pdbContent) {
    return (
      <div className="h-full w-full relative">
        <div className="absolute inset-0 flex items-center justify-center bg-white/80 z-10">
          <p className="text-muted-foreground">Load a complex to view structure</p>
        </div>
        <div className="h-full w-full" />
      </div>
    );
  }

  return (
    <div className="h-full w-full relative">
      <div 
        ref={containerRef} 
        className="h-full w-full"
        style={{ position: 'relative' }}
      />
    </div>
  );
}
