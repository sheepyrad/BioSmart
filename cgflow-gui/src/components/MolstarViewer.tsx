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
  ligandContent?: string | null;
  ligandLabel?: string | null;
  selectedResidues: string[];
  onResidueSelect: (residues: string[]) => void;
  /** If true, clicking always toggles. If false, requires Ctrl/Cmd for multi-select */
  multiSelectMode?: boolean;
}

export default function MolstarViewer({
  pdbContent,
  ligandContent = null,
  ligandLabel = null,
  selectedResidues,
  onResidueSelect,
  multiSelectMode = true, // Default to always toggle (multi-select)
}: MolstarViewerProps) {
  const molstarDisabledByEnv = ['true', '1', 'yes'].includes(
    String(import.meta.env.VITE_DISABLE_MOLSTAR ?? '').toLowerCase()
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const pluginRef = useRef<PluginUIContext | null>(null);
  const selectedResiduesRef = useRef<string[]>(selectedResidues);
  const onResidueSelectRef = useRef(onResidueSelect);
  const multiSelectModeRef = useRef(multiSelectMode);
  const [isInitialized, setIsInitialized] = useState(false);
  const [viewerError, setViewerError] = useState<string | null>(null);

  const supportsWebGL = () => {
    try {
      const canvas = document.createElement('canvas');
      return Boolean(
        canvas.getContext('webgl2') ||
          canvas.getContext('webgl') ||
          canvas.getContext('experimental-webgl')
      );
    } catch {
      return false;
    }
  };

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
    if (!containerRef.current || pluginRef.current || viewerError) return;

    async function init() {
      try {
        if (molstarDisabledByEnv) {
          setViewerError('Mol* viewer is disabled by environment setting.');
          return;
        }
        if (!supportsWebGL()) {
          setViewerError('WebGL is unavailable in this session. 3D viewer is disabled.');
          return;
        }

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
        setViewerError('Failed to initialize Mol* viewer (WebGL context unavailable).');
      }
    }

    init();

    return () => {
      pluginRef.current?.dispose();
      pluginRef.current = null;
    };
  }, [viewerError, molstarDisabledByEnv]);

  function inferLigandFormat(content: string, label: string | null): 'mol' | 'sdf' | 'mol2' | 'pdb' | 'mmcif' {
    const ext = (label ?? '').split('.').pop()?.toLowerCase();
    if (ext === 'sdf') return 'sdf';
    if (ext === 'mol2') return 'mol2';
    if (ext === 'mol') return 'mol';
    if (ext === 'pdb') return 'pdb';
    if (ext === 'cif' || ext === 'mmcif') return 'mmcif';
    if (content.includes('@<TRIPOS>MOLECULE')) return 'mol2';
    if (content.includes('$$$$')) return 'sdf';
    if (content.includes('M  END')) return 'mol';
    return 'pdb';
  }

  // Load structures when contents change
  useEffect(() => {
    if (molstarDisabledByEnv || !pluginRef.current || !pdbContent || !isInitialized) return;

    // Capture ligand content and label together to avoid race conditions
    const capturedLigandContent = ligandContent;
    const capturedLigandLabel = ligandLabel;

    const loadStructure = async () => {
      const plugin = pluginRef.current!;

      try {
        // Clear existing structures
        await plugin.clear();

        // Load protein structure from string
        const proteinData = await plugin.builders.data.rawData({
          data: pdbContent,
          label: 'protein-structure',
        });

        const trimmed = pdbContent.trim();
        const format = trimmed.startsWith('data_') || trimmed.includes('loop_') ? 'mmcif' : 'pdb';
        const proteinTrajectory = await plugin.builders.structure.parseTrajectory(proteinData, format as any);
        await plugin.builders.structure.hierarchy.applyPreset(proteinTrajectory, 'default');

        if (capturedLigandContent) {
          try {
            const ligandData = await plugin.builders.data.rawData({
              data: capturedLigandContent,
              label: capturedLigandLabel ?? 'reference-ligand',
            });
            const ligandFormat = inferLigandFormat(capturedLigandContent, capturedLigandLabel);
            const ligandTrajectory = await plugin.builders.structure.parseTrajectory(ligandData, ligandFormat as any);
            await plugin.builders.structure.hierarchy.applyPreset(ligandTrajectory, 'default');
          } catch (ligandError) {
            console.warn('Failed to load reference ligand content into viewer:', ligandError);
          }
        }

        // Reset camera to fit structure
        plugin.canvas3d?.requestCameraReset();
      } catch (err) {
        console.error('Failed to load structure:', err);
      }
    };

    loadStructure();
  }, [pdbContent, ligandContent, ligandLabel, isInitialized, molstarDisabledByEnv]);

  // Highlight selected residues
  useEffect(() => {
    if (molstarDisabledByEnv || !pluginRef.current || !isInitialized) return;
    
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
  }, [selectedResidues, isInitialized, molstarDisabledByEnv]);

  return (
    <div className="h-full w-full relative">
      {viewerError && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/95 z-20 p-4 text-center">
          <p className="text-sm text-muted-foreground">{viewerError}</p>
        </div>
      )}
      {!pdbContent && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/90 z-10">
          <div className="text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
              <svg className="h-6 w-6 text-primary/50" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </div>
            <p className="text-sm text-muted-foreground">Load a complex to view structure</p>
          </div>
        </div>
      )}
      <div 
        ref={containerRef} 
        className="h-full w-full"
        style={{ position: 'relative' }}
      />
    </div>
  );
}