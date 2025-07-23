import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
import py3Dmol
from rdkit import Chem
from rdkit.Chem import Draw
from rdkit.Chem import AllChem
import base64
import io
import os
import json
import time
import streamlit.components.v1 as components

# 3D Visualization Functions
def create_simple_3d_viewer(smiles_list, width=800, height=600):
    """
    Create a simple 3D viewer from SMILES strings as a fallback
    """
    try:
        import py3Dmol
        from rdkit import Chem
        from rdkit.Chem import AllChem
        
        view = py3Dmol.view(width=width, height=height)
        view.setBackgroundColor('white')
        
        model_count = 0
        for i, smiles in enumerate(smiles_list[:5]):  # Limit to 5 molecules
            try:
                mol = Chem.MolFromSmiles(smiles)
                if mol:
                    mol = Chem.AddHs(mol)
                    AllChem.EmbedMolecule(mol, randomSeed=42)
                    AllChem.UFFOptimizeMolecule(mol)
                    
                    pdb_block = Chem.MolToPDBBlock(mol)
                    view.addModel(pdb_block, 'pdb')
                    
                    # Color differently - use proper model index
                    colors = ['greenCarbon', 'cyanCarbon', 'magentaCarbon', 'yellowCarbon', 'orangeCarbon']
                    color = colors[model_count % len(colors)]
                    view.setStyle({'model': model_count}, {'stick': {'colorscheme': color, 'radius': 0.3}})
                    model_count += 1
            except Exception as mol_e:
                st.warning(f"Could not process SMILES {i}: {mol_e}")
                continue
        
        view.zoomTo()
        view.render()  # ✅ Critical: render before generating HTML
        return view._make_html()
        
    except Exception as e:
        st.error(f"Error in simple 3D viewer: {e}")
        return None

def render_unidock_result_3d(result_file_path, receptor_file=None):
    """
    Render Unidock docking result in 3D with multiple poses if available
    """
    try:
        # Check if required libraries are available
        try:
            import py3Dmol
            from rdkit import Chem
        except ImportError as e:
            st.error(f"❌ Required libraries not available: {e}")
            st.info("Install with: `pip install py3Dmol rdkit`")
            return None
        
        # Ensure result_file_path is a string or Path object, not a dict
        if isinstance(result_file_path, dict):
            st.error(f"❌ Invalid file path: received dict instead of file path")
            st.error(f"Debug info: {result_file_path}")
            return None
            
        result_path = Path(str(result_file_path))  # Ensure string conversion
        
        if not result_path.exists():
            st.error(f"❌ Result file not found: {result_path}")
            return None
            
        # Check file size to avoid loading extremely large files
        file_size = result_path.stat().st_size
        if file_size > 50 * 1024 * 1024:  # 50MB limit
            st.warning(f"⚠️ File is large ({file_size / 1024 / 1024:.1f} MB). Visualization may be slow.")
            
        view = py3Dmol.view(width=800, height=600)
        pose_count = 0
        model_index = 0  # Track model index explicitly throughout the function
        
        if result_path.suffix.lower() == '.sdf':
            # Handle SDF files with multiple poses
            try:
                from rdkit import Chem
                
                # Try to read the SDF file
                try:
                    suppl = Chem.SDMolSupplier(str(result_path), removeHs=False, sanitize=False)
                    
                    # Check if supplier is valid
                    if suppl is None:
                        st.error("❌ Failed to create molecule supplier from SDF file")
                        return None
                    
                    processed_molecules = 0
                    
                    for i, mol in enumerate(suppl):
                        try:
                            # Check what type of object we got from the supplier
                            if mol is not None:
                                # Validate that mol is actually an RDKit molecule object
                                if isinstance(mol, dict):
                                    st.error(f"❌ Got dict instead of molecule at position {i}: {mol}")
                                    continue
                                elif not hasattr(mol, 'GetNumAtoms'):
                                    st.error(f"❌ Invalid molecule object at position {i}, type: {type(mol)}")
                                    continue
                                    
                                processed_molecules += 1
                                pose_count += 1
                                
                                # Ensure the molecule has 3D coordinates
                                if mol.GetNumConformers() == 0:
                                    st.warning(f"⚠️ Molecule {i} has no 3D coordinates, generating them...")
                                    from rdkit.Chem import AllChem
                                    try:
                                        AllChem.EmbedMolecule(mol, randomSeed=42)
                                        AllChem.UFFOptimizeMolecule(mol)
                                    except Exception as embed_e:
                                        st.warning(f"⚠️ Could not generate 3D coordinates for molecule {i}: {embed_e}")
                                        continue
                                
                                # Convert to PDB format with error handling
                                try:
                                    # Validate molecule object before conversion
                                    if hasattr(mol, 'GetNumAtoms') and mol.GetNumAtoms() > 0:
                                        pdb_block = Chem.MolToPDBBlock(mol)
                                        if pdb_block and len(pdb_block.strip()) > 0:
                                            # Validate that we have a proper PDB block
                                            if isinstance(pdb_block, str):
                                                view.addModel(pdb_block, 'pdb')
                                                
                                                # Style each pose differently with more visible settings
                                                # Ensure model_index is an integer
                                                model_idx = int(model_index)
                                                
                                                if model_index == 0:
                                                    # Best pose in green with larger radius
                                                    style_selector = {'model': model_idx}
                                                    style_def = {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.4}}
                                                else:
                                                    # Other poses in different colors
                                                    colors = ['cyanCarbon', 'magentaCarbon', 'yellowCarbon', 'orangeCarbon']
                                                    color = colors[min(model_index-1, len(colors)-1)]
                                                    style_selector = {'model': model_idx}
                                                    style_def = {'stick': {'colorscheme': color, 'radius': 0.3, 'opacity': 0.8}}
                                                
                                                # Apply styling with validation
                                                try:
                                                    view.setStyle(style_selector, style_def)
                                                except Exception as style_e:
                                                    st.error(f"❌ Error styling model {model_index}: {style_e}")
                                                
                                                model_index += 1
                                            else:
                                                st.error(f"❌ PDB block is not a string for molecule {i}, got {type(pdb_block)}")
                                        else:
                                            st.warning(f"⚠️ Could not convert molecule {i} to PDB format or empty PDB block")
                                    else:
                                        st.warning(f"⚠️ Molecule {i} has no atoms or is invalid")
                                except Exception as pdb_e:
                                    st.error(f"❌ PDB conversion error for molecule {i}: {pdb_e}")
                                    continue
                            else:
                                st.warning(f"⚠️ Invalid molecule at position {i} in SDF file")
                        except Exception as mol_e:
                            st.error(f"❌ Error processing molecule {i}: {mol_e}")
                            continue
                    
                    if pose_count == 0:
                        st.error("❌ No valid poses found in SDF file")
                        return None
                        
                except Exception as sdf_e:
                    st.error(f"❌ Error reading SDF file: {sdf_e}")
                    return None
                    
            except ImportError:
                st.error("❌ RDKit is required to display SDF files")
                st.info("Install with: `pip install rdkit`")
                return None
            except Exception as e:
                st.error(f"❌ Error processing SDF file: {e}")
                return None
                
        elif result_path.suffix.lower() == '.pdbqt':
            # Handle PDBQT files with multiple models
            with open(result_path) as f:
                pdbqt_data = f.read()
            
            # Split into individual models if multiple exist
            models = pdbqt_data.split('MODEL')
            
            for i, model_data in enumerate(models):
                if model_data.strip():
                    if i > 0:  # Skip the first empty split
                        model_data = 'MODEL' + model_data
                    
                    view.addModel(model_data, 'pdbqt')
                    
                    # Style each model - use correct model index with validation
                    model_idx = int(model_index)
                    
                    if model_index == 0:  # First actual model (best pose)
                        style_selector = {'model': model_idx}
                        style_def = {'stick': {'colorscheme': 'greenCarbon', 'radius': 0.3}}
                    else:
                        colors = ['cyanCarbon', 'magentaCarbon', 'yellowCarbon', 'orangeCarbon']
                        color = colors[min(model_index-1, len(colors)-1)]
                        style_selector = {'model': model_idx}
                        style_def = {'stick': {'colorscheme': color, 'radius': 0.2, 'opacity': 0.7}}
                    
                    # Apply styling with error handling
                    try:
                        view.setStyle(style_selector, style_def)
                    except Exception as style_e:
                        st.error(f"❌ Error styling PDBQT model {model_index}: {style_e}")
                    
                    model_index += 1
                    pose_count += 1
        
        # Add receptor if provided
        if receptor_file and Path(receptor_file).exists():
            try:
                receptor_model_index = model_index  # This will be the next model index
                
                with open(receptor_file) as f:
                    receptor_data = f.read()
                
                if not receptor_data.strip():
                    st.error("❌ Receptor file is empty")
                    raise ValueError("Empty receptor file")
                
                receptor_format = 'pdbqt' if str(receptor_file).lower().endswith('.pdbqt') else 'pdb'
                view.addModel(receptor_data, receptor_format)
                
                # Create style dictionary with higher opacity for more distinct receptor
                model_selector = {'model': int(receptor_model_index)}
                style_dict = {
                    'cartoon': {'color': 'spectrum', 'opacity': 0.8},  # Increased to 0.8 for more distinction
                    'line': {'hidden': True}
                }
                
                view.setStyle(model_selector, style_dict)
                
                # Add binding site surface with more visible opacity
                surface_style = {'opacity': 0.3, 'color': 'lightblue'}  # Increased to 0.3 for more visibility
                surface_selector = {'model': int(receptor_model_index)}
                
                view.addSurface(py3Dmol.VDW, surface_style, surface_selector)
                
                # Update model index after adding the receptor
                model_index += 1
                    
            except Exception as receptor_e:
                st.error(f"❌ Error adding receptor: {receptor_e}")
                st.warning("🔄 Continuing without receptor...")
        
        # Set view options and ensure molecules are visible
        view.setBackgroundColor('white')
        
        # Add informative labels
        if pose_count > 0:
            view.addLabel(f"Poses: {pose_count}", {
                'position': {'x': 0, 'y': 0, 'z': 5}, 
                'backgroundColor': 'green', 
                'fontColor': 'white',
                'fontSize': 12
            })
        
        # Set view options before final render
        view.zoomTo()  # Zoom to fit all molecules
        view.center()  # Center the view
        
        # Critical: render before generating HTML
        view.render()
        
        # Optional: adjust zoom level after render if needed
        # view.zoom(1.2)  # Slightly zoom out for better view
        
        # Generate HTML and add some debugging
        html_content = view._make_html()
        
        # Replace the default CDN with a more reliable one
        html_content = html_content.replace(
            'https://cdnjs.cloudflare.com/ajax/libs/3Dmol/2.0.1/3Dmol-min.js',
            'https://unpkg.com/3dmol@latest/build/3Dmol-min.js'
        )
        
        # Add fallback CDN in case the first one fails
        fallback_script = '''
        <script>
        if (typeof $3Dmol === 'undefined') {
            console.log('Primary 3Dmol CDN failed, trying fallback...');
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/3dmol@latest/build/3Dmol-min.js';
            script.onload = function() {
                console.log('Fallback 3Dmol CDN loaded successfully');
                // Reinitialize the viewer after fallback loads
                if (window.viewer) {
                    window.viewer.render();
                }
            };
            script.onerror = function() {
                console.error('Both 3Dmol CDNs failed to load');
                document.getElementById('3dmolviewer_UNIQUE_ID').innerHTML = 
                    '<div style="text-align:center; padding:50px; color:#f56565;">' +
                    '❌ 3Dmol.js failed to load from CDN<br>' +
                    'Please check your internet connection or browser settings</div>';
            };
            document.head.appendChild(script);
        }
        </script>
        '''
        
        # Insert the fallback script before the closing body tag
        html_content = html_content.replace('</body>', fallback_script + '</body>')
        

        
        return html_content
        
    except Exception as e:
        st.error(f"Error rendering Unidock result: {e}")
        return None

def create_interactive_3d_viewer(result_data, output_dir_path):
    """
    Create an interactive 3D viewer for docking results with pose selection
    """
    try:
        variant_id = result_data.get('variant_id', result_data.get('compound_id', 'Unknown'))
        barcode = result_data.get('barcode', 'Unknown')
        round_num = result_data.get('round', 1)
        
        # Try to find result files
        result_file = result_data.get('result_file')
        
        # User input for receptor file path
        st.markdown("#### 🔬 Receptor File Configuration")
        receptor_file_path = st.text_input(
            "Receptor File Path (optional)",
            placeholder="Enter path to receptor file (.pdbqt or .pdb)",
            help="Provide the full path to your receptor file for protein-ligand visualization",
            key=f"receptor_path_{variant_id}"
        )
        
        receptor_file = None
        if receptor_file_path and receptor_file_path.strip():
            receptor_path = Path(receptor_file_path.strip())
            if receptor_path.exists():
                receptor_file = receptor_path
                st.success(f"✅ Receptor file found: {receptor_path.name}")
            else:
                st.error(f"❌ Receptor file not found: {receptor_path}")
                st.info("💡 Please check the file path and ensure the file exists")
        elif hasattr(st.session_state, 'global_receptor_file') and st.session_state.global_receptor_file:
            # Use global receptor file if no local one is provided
            receptor_file = Path(st.session_state.global_receptor_file)
            st.info(f"📋 Using global receptor file: {receptor_file.name}")
        else:
            st.info("💡 No receptor file specified - ligand will be displayed without protein context")
        
        # Try to find the result file if not provided
        if not result_file or not Path(result_file).exists():
            # Try to construct the result file path
            if barcode and round_num:
                possible_result_paths = [
                    output_dir_path / f"round_{round_num}" / "docking_results" / f"variant_{barcode}" / "unidock_out.sdf",
                    output_dir_path / f"round_{round_num}" / "docking_results" / f"variant_{barcode}" / "poses.sdf",
                    output_dir_path / f"round_{round_num}" / "docking_results" / f"variant_{barcode}" / "result.sdf",
                    output_dir_path / f"round_{round_num}" / "docking_results" / f"{variant_id}.sdf",
                    output_dir_path / f"round_{round_num}" / "docking_results" / f"{barcode}.sdf"
                ]
                
                for path in possible_result_paths:
                    if path.exists():
                        result_file = str(path)
                        break
        
        if result_file and Path(result_file).exists():
            st.markdown("### 🧬 3D Molecular Visualization")
            
            # Create tabs for different views
            tab1, tab2, tab3 = st.tabs(["📊 Docking Result", "🔬 Ligand Only", "📋 Information"])
            
            with tab1:
                st.markdown("**Docking Result with Receptor**")
                if receptor_file:
                    try:
                        # Ensure we're passing strings, not other data types
                        result_file_str = str(result_file) if result_file else None
                        receptor_file_str = str(receptor_file) if receptor_file else None
                        
                        html_content = render_unidock_result_3d(result_file_str, receptor_file_str)
                        if html_content:
                            components.html(html_content, height=600, width=800)
                            st.caption("🟢 Best pose | 🔵🟣🟡🟠 Alternative poses | 🌈 Protein receptor")
                        else:
                            st.error("❌ Failed to render 3D structure with receptor")
                    except Exception as e:
                        st.error(f"❌ Error rendering 3D structure: {str(e)}")
                        st.info("🔄 Falling back to ligand-only view...")
                        try:
                            result_file_str = str(result_file) if result_file else None
                            html_content = render_unidock_result_3d(result_file_str)
                            if html_content:
                                components.html(html_content, height=600, width=800)
                        except Exception as e2:
                            st.error(f"❌ Also failed to render ligand-only: {str(e2)}")
                else:
                    st.info("📍 Showing ligand without receptor context")
                    try:
                        result_file_str = str(result_file) if result_file else None
                        html_content = render_unidock_result_3d(result_file_str)
                        if html_content:
                            components.html(html_content, height=600, width=800)
                        else:
                            st.error("❌ Failed to render ligand structure")
                    except Exception as e:
                        st.error(f"❌ Error rendering ligand: {str(e)}")
            
            with tab2:
                st.markdown("**Ligand Structure Only**")
                try:
                    result_file_str = str(result_file) if result_file else None
                    html_content = render_unidock_result_3d(result_file_str)
                    if html_content:
                        # Show a preview of the HTML content
                        if st.checkbox("🔍 Show HTML preview", key=f"show_html_{variant_id}"):
                            st.code(html_content[:500] + "..." if len(html_content) > 500 else html_content, language="html")
                        
                        components.html(html_content, height=600, width=800)
                        st.caption("🟢 Best pose | 🔵🟣🟡🟠 Alternative poses")
                    else:
                        st.error("❌ Failed to render ligand structure from SDF file")
                        
                        # Try alternative visualization methods
                        if "smiles" in result_data and result_data["smiles"]:
                            visualization_options = st.radio(
                                "Choose visualization method:",
                                ["🔄 Try simple 3D (SMILES)", "📄 2D Structure", "🎨 RDKit 3D Plot"],
                                key=f"viz_option_{variant_id}"
                            )
                            
                            if visualization_options == "🔄 Try simple 3D (SMILES)":
                                st.info("🔄 Trying simple 3D visualization from SMILES...")
                                simple_html = create_simple_3d_viewer([result_data["smiles"]])
                                if simple_html:
                                    components.html(simple_html, height=400, width=600)
                                    st.caption("3D structure generated from SMILES")
                                else:
                                    st.error("❌ 3D visualization failed")
                            
                            elif visualization_options == "📄 2D Structure":
                                st.info("📄 Showing 2D molecular structure:")
                                mol_img = render_mol(result_data["smiles"])
                                if mol_img:
                                    st.image(mol_img, caption="2D Molecular Structure", width=200)
                                else:
                                    st.text(f"SMILES: {result_data['smiles']}")
                            
                            elif visualization_options == "🎨 RDKit 3D Plot":
                                st.info("🎨 Creating 3D plot with RDKit and Plotly...")
                                try:
                                    from rdkit import Chem
                                    from rdkit.Chem import AllChem
                                    import plotly.graph_objects as go
                                    
                                    mol = Chem.MolFromSmiles(result_data["smiles"])
                                    if mol:
                                        mol = Chem.AddHs(mol)
                                        AllChem.EmbedMolecule(mol, randomSeed=42)
                                        AllChem.UFFOptimizeMolecule(mol)
                                        
                                        # Get atom coordinates
                                        conf = mol.GetConformer()
                                        atoms = []
                                        x_coords, y_coords, z_coords = [], [], []
                                        
                                        for atom in mol.GetAtoms():
                                            pos = conf.GetAtomPosition(atom.GetIdx())
                                            x_coords.append(pos.x)
                                            y_coords.append(pos.y)
                                            z_coords.append(pos.z)
                                            atoms.append(atom.GetSymbol())
                                        
                                        # Create 3D scatter plot
                                        fig = go.Figure(data=[go.Scatter3d(
                                            x=x_coords, y=y_coords, z=z_coords,
                                            mode='markers+text',
                                            marker=dict(size=8, color=atoms, colorscale='viridis'),
                                            text=atoms,
                                            textposition="middle center"
                                        )])
                                        
                                        # Add bonds
                                        bond_x, bond_y, bond_z = [], [], []
                                        for bond in mol.GetBonds():
                                            start_idx = bond.GetBeginAtomIdx()
                                            end_idx = bond.GetEndAtomIdx()
                                            start_pos = conf.GetAtomPosition(start_idx)
                                            end_pos = conf.GetAtomPosition(end_idx)
                                            
                                            bond_x.extend([start_pos.x, end_pos.x, None])
                                            bond_y.extend([start_pos.y, end_pos.y, None])
                                            bond_z.extend([start_pos.z, end_pos.z, None])
                                        
                                        fig.add_trace(go.Scatter3d(
                                            x=bond_x, y=bond_y, z=bond_z,
                                            mode='lines',
                                            line=dict(color='gray', width=3),
                                            showlegend=False
                                        ))
                                        
                                        fig.update_layout(
                                            title="3D Molecular Structure (RDKit + Plotly)",
                                            scene=dict(aspectmode='cube'),
                                            showlegend=False
                                        )
                                        
                                        st.plotly_chart(fig, use_container_width=True)
                                        st.success("✅ 3D structure plotted with RDKit and Plotly")
                                    else:
                                        st.error("❌ Could not parse SMILES")
                                except Exception as e:
                                    st.error(f"❌ RDKit 3D plot failed: {e}")
                                    st.info("📄 Fallback to 2D:")
                                    mol_img = render_mol(result_data["smiles"])
                                    if mol_img:
                                        st.image(mol_img, caption="2D Molecular Structure")
                except Exception as e:
                    st.error(f"❌ Error rendering ligand: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
                    # Show SMILES as fallback
                    if "smiles" in result_data and result_data["smiles"]:
                        st.info("📄 Showing 2D structure as fallback:")
                        mol_img = render_mol(result_data["smiles"])
                        if mol_img:
                            st.image(mol_img, caption="2D Molecular Structure")
            
            with tab3:
                st.markdown("**File Information**")
                file_info = {
                    "Result File": str(Path(result_file).name),
                    "File Size": f"{Path(result_file).stat().st_size / 1024:.1f} KB",
                    "File Type": Path(result_file).suffix.upper(),
                    "Receptor File": str(Path(receptor_file).name) if receptor_file else "Not provided"
                }
                
                if "pose_count" in result_data:
                    file_info["Pose Count"] = result_data["pose_count"]
                
                if "all_scores" in result_data and result_data["all_scores"]:
                    try:
                        all_scores_str = str(result_data["all_scores"])
                        if all_scores_str.startswith('[') and all_scores_str.endswith(']'):
                            import ast
                            all_scores = ast.literal_eval(all_scores_str)
                            file_info["Score Range"] = f"{min(all_scores):.2f} to {max(all_scores):.2f}"
                    except:
                        pass
                
                st.json(file_info)
                
                # Download buttons
                col1, col2 = st.columns(2)
                with col1:
                    try:
                        with open(result_file, 'rb') as f:
                            file_data = f.read()
                        st.download_button(
                            "📥 Download Result File",
                            data=file_data,
                            file_name=Path(result_file).name,
                            mime="application/octet-stream",
                            key=f"download_result_{variant_id}"
                        )
                    except Exception as e:
                        st.error(f"❌ Cannot read result file: {str(e)}")
                
                with col2:
                    if receptor_file and Path(receptor_file).exists():
                        try:
                            with open(receptor_file, 'rb') as f:
                                receptor_data = f.read()
                            st.download_button(
                                "📥 Download Receptor",
                                data=receptor_data,
                                file_name=Path(receptor_file).name,
                                mime="application/octet-stream",
                                key=f"download_receptor_{variant_id}"
                            )
                        except Exception as e:
                            st.error(f"❌ Cannot read receptor file: {str(e)}")
        else:
            st.warning("❌ No 3D structure file available for this result")
            st.info("🔍 Searched for result files but none were found.")
            

            
            # Show 2D structure as fallback if SMILES is available
            if "smiles" in result_data and result_data["smiles"]:
                st.info("📄 Showing 2D structure instead:")
                mol_img = render_mol(result_data["smiles"])
                if mol_img:
                    st.image(mol_img, caption="2D Molecular Structure", use_container_width=True)
                else:
                    st.text(f"SMILES: {result_data['smiles']}")
            else:
                st.text("No molecular structure data available")
            
    except Exception as e:
        st.error(f"Error creating 3D viewer: {e}")
        import traceback
        st.code(traceback.format_exc())

# Function to render molecule
def render_mol(smiles, width=250, height=200):
    """Render molecule using RDKit"""
    try:
        if smiles is None or pd.isna(smiles) or smiles == "":
            st.warning("No valid SMILES string provided")
            return None
            
        # Clean the SMILES string
        smiles = str(smiles).strip()
        
        # Try to generate the molecule
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            st.warning(f"Could not parse SMILES: {smiles}")
            return None
            
        # Generate 2D coordinates if they don't exist
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
            
        # Create the image
        img = Draw.MolToImage(mol, size=(width, height))
        return img
    except Exception as e:
        st.error(f"Error rendering molecule: {str(e)}")
        return None

# Function to load results
def load_results(output_dir):
    """Load results from the output directory"""
    output_dir = Path(output_dir)
    results = {
        "tracking_report": None
    }
    
    # Load tracking report
    tracking_file = output_dir / "master_tracking" / "master_compound_tracking_report.csv"
    
    if tracking_file.exists():
        try:
            results["tracking_report"] = pd.read_csv(tracking_file)
            st.success("Successfully loaded tracking report.")
        except Exception as e:
            st.error(f"Error reading tracking report: {str(e)}")
            import traceback
            st.code(traceback.format_exc())
    else:
        st.warning(f"Tracking report not found at: {tracking_file}")
    
    return results

# Function to create downloadable link
def get_download_link(df, filename, text):
    """Create a download link for a dataframe"""
    csv = df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    href = f'<a href="data:file/csv;base64,{b64}" download="{filename}">{text}</a>'
    return href

# Page configuration
st.set_page_config(
    page_title="Visualize Results",
    page_icon="🔍",
    layout="wide"
)

# Add custom CSS for consistent styling across both pages
st.markdown("""
    <style>
    .main {
        padding: 0rem 1rem;
    }
    .stApp {
        max-width: 100%;
        margin: 0 auto;
    }
    .block-container {
        max-width: 100%;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .st-emotion-cache-1v0mbdj {
        width: 100%;
    }
    
    /* Dashboard-specific styling */
    .dashboard-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
    }
    
    .analysis-header {
        background: linear-gradient(90deg, #11998e 0%, #38ef7d 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1rem;
    }
    
    .metric-container {
        background: white;
        padding: 1rem;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 4px solid #11998e;
        color: #2c3e50;
    }
    
    .metric-container h4 {
        color: #34495e;
        margin: 0 0 0.5rem 0;
        font-size: 1rem;
        font-weight: 600;
    }
    
    .metric-container h2 {
        margin: 0.5rem 0;
        font-size: 2rem;
        font-weight: bold;
    }
    
    .metric-container small {
        color: #7f8c8d;
        font-size: 0.875rem;
    }
    
    .status-indicator {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        margin-right: 8px;
    }
    
    .status-running { background-color: #ffd93d; }
    .status-complete { background-color: #6bff6b; }
    .status-pending { background-color: #d3d3d3; }
    .status-error { background-color: #ff6b6b; }
    
    .pipeline-stage {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        transition: all 0.3s ease;
    }
    
    .pipeline-stage:hover {
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        transform: translateY(-2px);
    }
    
    .analysis-indicator {
        color: #11998e;
        font-weight: bold;
    }
    
    <style>
    .metric-card {
        background: linear-gradient(90deg, #4a5568 0%, #2d3748 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .success-card {
        background: linear-gradient(90deg, #38a169 0%, #48bb78 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .info-card {
        border-left: 4px solid #38a169;
        color: #e2e8f0;
        padding: 1rem;
        margin: 1rem 0;
    }
    .info-card h3 {
        color: #e2e8f0;
        margin-top: 0;
    }
    .info-card p {
        margin-bottom: 0;
    }
    .small-text {
        font-size: 0.9em;
        color: #a0aec0;
    }
    .status-running { background-color: #ed8936; }
    .status-complete { background-color: #48bb78; }
    .status-pending { background-color: #4a5568; }
    .status-error { background-color: #f56565; }
    
    .log-container {
        background: #1a202c;
        border: 1px solid #4a5568;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .highlight {
        color: #38a169;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# Header for visualization page
st.markdown("""
    <div class="analysis-header">
        <h1>🔍 Visualize Pipeline Results <span class="analysis-indicator">📈</span></h1>
        <p>Load and explore any completed pipeline output directory</p>
    </div>
""", unsafe_allow_html=True)

# Add information about analysis capabilities
with st.expander("🔬 Analysis Features", expanded=False):
    st.markdown("""
    **Comprehensive Analysis Capabilities:**
    
    📊 **Deep Data Exploration**
    - Load and analyze any completed pipeline output
    - Advanced filtering and sorting across all data dimensions
    - Pagination for large datasets with configurable views
    
    🎯 **Detailed Visualizations**
    - Interactive 3D molecular structure viewers
    - Multi-dimensional plotting and correlation analysis
    - Custom dashboard views for different analysis needs
    
    📈 **Statistical Analysis**
    - Distribution analysis for docking scores and affinity predictions
    - Correlation analysis between different metrics
    - Performance comparisons across pipeline rounds
    
    🧬 **Enhanced 3D Visualization:**
    - 🟢 Best poses highlighted in green
    - 🔵🟣🟡🟠 Alternative poses color-coded  
    - 🌈 Protein receptor with binding surface
    - Interactive controls with download capabilities
    
    **💾 Export & Sharing:**
    - Download filtered datasets in multiple formats
    - Export 3D structures for external analysis
    - Generate summary reports and statistics
    
    **🔍 Flexible Data Input:**
    - Manual directory path entry
    - Automatic detection of pipeline structure
    - Support for multiple output formats
    
    **🔬 Receptor File Configuration:**
    - Set a global receptor file in the sidebar for all visualizations
    - Override with specific receptor files for individual compounds
    - Supports both .pdbqt and .pdb formats
    """)
    
    # Check library availability
    try:
        import py3Dmol
        from rdkit import Chem
        st.success("✅ All analysis libraries available (py3Dmol, RDKit)")
    except ImportError as e:
        st.warning(f"⚠️ Missing libraries: {e}")
        st.info("Install with: `pip install py3Dmol rdkit`")

# Initialize session state variables
if "output_dir" not in st.session_state:
    st.session_state.output_dir = None

if "results_data" not in st.session_state:
    st.session_state.results_data = None

if "selected_view" not in st.session_state:
    st.session_state.selected_view = "Summary"

# Directory selection
st.markdown("## 📁 Select Pipeline Output Directory")

st.info("Enter the path to any completed pipeline output directory for visualization")

# Enter path manually
dir_path = st.text_input(
    "Output Directory Path:", 
    placeholder="/path/to/outputs/pipeline_run_name",
    help="Enter the full path to a pipeline output directory containing results to visualize"
)

# Process manually entered path
if dir_path:
    output_dir_path = Path(dir_path)
    if output_dir_path.exists() and output_dir_path.is_dir():
        st.success(f"✅ Directory Found: {output_dir_path}")
        st.session_state.output_dir = output_dir_path
        
        # Auto-load results when valid directory is found
        with st.spinner("🔄 Loading results..."):
            try:
                results = load_results(st.session_state.output_dir)
                if results is not None and results.get("tracking_report") is not None:
                    st.session_state.results_data = results
                    st.success("✅ Successfully loaded results!")
                else:
                    st.warning("⚠️ No tracking report found. The pipeline may still be running or incomplete.")
                    st.session_state.results_data = results  # Keep partial results
            except Exception as e:
                st.error(f"❌ Error processing results: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
    else:
        st.error(f"❌ Directory not found: {output_dir_path}")
        st.session_state.output_dir = None
        st.session_state.results_data = None
else:
    st.warning("📁 Please enter a valid pipeline output directory path above to start visualization.")
    st.info("💡 **Tip:** Look for directories containing 'master_tracking' or 'round_*' subdirectories.")
    st.session_state.results_data = None

# Navigation and main content
if st.session_state.results_data and st.session_state.results_data.get("tracking_report") is not None:
    df = st.session_state.results_data["tracking_report"]
    
    # Enhanced Sidebar for navigation
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #38a169 0%, #48bb78 100%); border-radius: 10px; color: white; margin-bottom: 1rem;">
                <h3>📊 VISUALIZATION MODE</h3>
                <p style="margin: 0; font-size: 0.9em;">Interactive exploration</p>
            </div>
        """, unsafe_allow_html=True)
        
        st.session_state.selected_view = st.radio(
            "📊 Dashboard Views",
            ["Summary", "Compounds", "Variants", "Docking Results"],
            help="Select different views of your pipeline data"
        )
        
        st.divider()
        
        # Global Receptor File Configuration
        st.subheader("🔬 Global Receptor File")
        global_receptor_path = st.text_input(
            "Receptor File Path",
            placeholder="Enter path to receptor file (.pdbqt or .pdb)",
            help="Set a global receptor file path to use for all 3D visualizations on this page",
            key="global_receptor_path_viz"
        )
        
        if global_receptor_path and global_receptor_path.strip():
            receptor_test_path = Path(global_receptor_path.strip())
            if receptor_test_path.exists():
                st.success(f"✅ Global receptor file set: {receptor_test_path.name}")
                # Store in session state for use by visualization functions
                st.session_state.global_receptor_file = str(receptor_test_path)
            else:
                st.error(f"❌ Receptor file not found")
                st.session_state.global_receptor_file = None
        else:
            st.info("💡 No global receptor file set")
            st.session_state.global_receptor_file = None
        
        st.divider()
        
        # Sidebar filtering options (global)
        st.subheader("🎛️ Global Filters")
        
        # Round filter (applies to all views)
        if "round" in df.columns:
            try:
                round_options = sorted([r for r in df["round"].unique() if pd.notna(r)])
                sidebar_rounds = st.multiselect(
                    "Filter by Round",
                    options=round_options,
                    default=round_options,
                    key="sidebar_rounds_viz"
                )
            except Exception as e:
                st.error(f"Error loading round options: {e}")
                sidebar_rounds = []
        else:
            st.info("Round information not available for filtering")
            sidebar_rounds = []
        
        # Status filter
        if "status" in df.columns:
            try:
                status_options = sorted([s for s in df["status"].unique() if pd.notna(s)])
                sidebar_status = st.multiselect(
                    "Filter by Status",
                    options=status_options,
                    default=status_options,
                    key="sidebar_status_viz"
                )
            except Exception as e:
                st.error(f"Error loading status options: {e}")
                sidebar_status = []
        else:
            st.info("Status information not available for filtering")
            sidebar_status = []
        
        # Apply global filters
        if sidebar_rounds and sidebar_status and "round" in df.columns and "status" in df.columns:
            try:
                filtered_df = df[df["round"].isin(sidebar_rounds) & df["status"].isin(sidebar_status)]
            except Exception as e:
                st.error(f"Error applying filters: {e}")
                filtered_df = df
        else:
            filtered_df = df
            
    # Add refresh button
    if st.button("🔄 Refresh Data"):
        if st.session_state.output_dir:
            with st.spinner("Refreshing data..."):
                results = load_results(st.session_state.output_dir)
                if results is not None:
                    st.session_state.results_data = results
                    st.success("Data refreshed successfully!")
                    st.rerun()
                else:
                    st.error("Failed to refresh data.")
            
    # Main content - Conditional rendering based on the selected view
    # Check if we have any data at all
    if df.empty:
        st.warning("The tracking report is empty. The pipeline may still be in the initial stages.")
    else:
        # Continue with regular view rendering based on selected view
        # Define available_statuses for use across all views
        available_statuses = df["status"].unique() if "status" in df.columns else []
                
        if st.session_state.selected_view == "Summary":
            st.markdown("## 📊 Pipeline Overview")
            
            # Enhanced Summary metrics with styling
            st.markdown("### 🔢 Key Metrics")
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                compound_count = len(df[df["status"] == "GENERATED"]) if "status" in df.columns else 0
                st.markdown(f"""
                    <div class="metric-container">
                        <h4>🧬 Compounds</h4>
                        <h2 style="color: #48bb78; margin: 0;">{compound_count}</h2>
                        <small>Generated</small>
                    </div>
                """, unsafe_allow_html=True)
            with col2:
                variant_count = len(df[df["status"] == "SYNTHETIZED"]) if "status" in df.columns else 0
                st.markdown(f"""
                    <div class="metric-container">
                        <h4>⚗️ Variants</h4>
                        <h2 style="color: #48bb78; margin: 0;">{variant_count}</h2>
                        <small>Synthesized</small>
                    </div>
                """, unsafe_allow_html=True)
            with col3:
                filtered_count = len(
                    df[df["status"].isin(["PASSFILTER", "PASSBLINDDOCK"])]
                ) if "status" in df.columns else 0
                st.markdown(f"""
                    <div class="metric-container">
                        <h4>🔬 Filtered</h4>
                        <h2 style="color: #48bb78; margin: 0;">{filtered_count}</h2>
                        <small>Passed filters</small>
                    </div>
                """, unsafe_allow_html=True)
            with col4:
                docked_count = len(df[df["status"] == "DOCKED"]) if "status" in df.columns else 0
                st.markdown(f"""
                    <div class="metric-container">
                        <h4>🎯 Docked</h4>
                        <h2 style="color: #48bb78; margin: 0;">{docked_count}</h2>
                        <small>Completed</small>
                    </div>
                """, unsafe_allow_html=True)
            with col5:
                # Show best docking score if available (lower is better)
                if "docking_score" in df.columns and df["docking_score"].notna().any():
                    best_score = df[df["docking_score"].notna()]["docking_score"].min()
                    score_text = f"{best_score:.2f}"
                else:
                    score_text = "N/A"
                st.markdown(f"""
                    <div class="metric-container">
                        <h4>🏆 Best Score</h4>
                        <h2 style="color: #48bb78; margin: 0;">{score_text}</h2>
                        <small>Lower = better</small>
                    </div>
                """, unsafe_allow_html=True)
                        
            # Workflow Progress Visualization
            st.subheader("Workflow Progress")
            
            # Define workflow stages
            workflow_stages = [
                ("Generation", "GENERATED", "🧬"),
                ("Retrosynthesis", "SYNTHETIZED", "⚗️"),
                ("MedChem Filter", "PASSFILTER", "🔬"),
                ("Boltz Filter", "PASSBLINDDOCK", "🤖"),
                ("Docking", "DOCKED", "🎯")
            ]
            
            # Create progress indicators
            progress_cols = st.columns(len(workflow_stages))
            
            for i, (stage_name, status_key, emoji) in enumerate(workflow_stages):
                with progress_cols[i]:
                    count = len(df[df["status"] == status_key]) if "status" in df.columns else 0
                    is_complete = status_key in available_statuses and count > 0
                    
                    if is_complete:
                        st.success(f"{emoji} {stage_name}")
                        st.write(f"**{count}** items")
                    else:
                        st.info(f"{emoji} {stage_name}")
                        st.write("Pending")
            
            # Show detailed progress message
            progress_message = ""
            if "GENERATED" in available_statuses and "SYNTHETIZED" not in available_statuses:
                progress_message = "Pipeline has generated compounds but not yet completed retrosynthesis."
            elif "SYNTHETIZED" in available_statuses and "PASSFILTER" not in available_statuses:
                progress_message = "Pipeline has generated variants but not yet completed filtering."
            elif "PASSFILTER" in available_statuses and "DOCKED" not in available_statuses:
                progress_message = "Pipeline has filtered variants but not yet completed docking."
            elif "DOCKED" in available_statuses:
                progress_message = "Pipeline has completed all major stages successfully!"
            
            if progress_message:
                if "completed all major stages" in progress_message:
                    st.success(progress_message)
                else:
                    st.info(progress_message + " Some visualizations may not be available until those steps complete.")
            
            # Affinity Analysis Section
            if "affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any():
                st.subheader("🤖 Boltz-2 Affinity Analysis")
                
                # Add explanation of the two metrics
                with st.expander("📖 Understanding Boltz-2 Affinity Predictions", expanded=False):
                    st.markdown("""
                    **Two Types of Predictions:**
                    
                    🎯 **Affinity Probability Binary** (0-1 scale):
                    - Used for **hit discovery** to detect binders from decoys
                    - Values closer to 1 indicate higher probability of binding
                    - Threshold: >0.5 typically indicates a predicted binder
                    
                    📊 **Affinity Prediction Value** (log(IC50) scale):
                    - Used for **ligand optimization** (hit-to-lead, lead-optimization)
                    - Reports binding affinity as log(IC50) where IC50 is in μM
                    - **Lower values = stronger binding**
                    - Examples:
                        - -3: Strong binder (IC50 ~ 10⁻⁹ M)
                        - 0: Moderate binder (IC50 ~ 10⁻⁶ M) 
                        - 2: Weak binder/decoy (IC50 ~ 10⁻⁴ M)
                    
                    🔄 **Conversions:**
                    - To IC50 in μM: IC50 = 10^(log(IC50))
                    - To pIC50 in kcal/mol: pIC50 = (6 - log(IC50)) × 1.364
                    """)
                
                affinity_with_values = df[df["affinity_pred_value"].notna()]
                if not affinity_with_values.empty:
                    # Create metrics for affinity predictions
                    aff_col1, aff_col2, aff_col3, aff_col4 = st.columns(4)
                    with aff_col1:
                        best_affinity = affinity_with_values["affinity_pred_value"].min()  # Lower log(IC50) is better
                        st.metric("Best log(IC50) (lower=better)", f"{best_affinity:.3f}")
                    with aff_col2:
                        avg_affinity = affinity_with_values["affinity_pred_value"].mean()
                        st.metric("Average log(IC50)", f"{avg_affinity:.3f}")
                    with aff_col3:
                        if "affinity_probability_binary" in affinity_with_values.columns:
                            high_prob_count = len(affinity_with_values[affinity_with_values["affinity_probability_binary"] > 0.5])
                            st.metric("Predicted Binders", f"{high_prob_count}/{len(affinity_with_values)}")
                        else:
                            st.metric("Predictions", len(affinity_with_values))
                    with aff_col4:
                        if "affinity_probability_binary" in affinity_with_values.columns:
                            avg_prob = affinity_with_values["affinity_probability_binary"].mean()
                            st.metric("Avg Binding Prob", f"{avg_prob:.3f}")
                        else:
                            median_affinity = affinity_with_values["affinity_pred_value"].median()
                            st.metric("Median log(IC50)", f"{median_affinity:.3f}")
                    
                    # Create visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Affinity value distribution
                        fig_aff = px.histogram(
                            affinity_with_values,
                            x="affinity_pred_value",
                            nbins=20,
                            title="Distribution of log(IC50) Predictions (Lower = Better)",
                            color_discrete_sequence=["#00cc96"],
                            labels={"affinity_pred_value": "log(IC50) Prediction", "count": "Number of Compounds"}
                        )
                        fig_aff.update_layout(bargap=0.1)
                        st.plotly_chart(fig_aff, use_container_width=True)
                    
                    with viz_col2:
                        # Affinity vs Probability scatter plot if probability data exists
                        if "affinity_probability_binary" in affinity_with_values.columns:
                            fig_scatter = px.scatter(
                                affinity_with_values,
                                x="affinity_pred_value",
                                y="affinity_probability_binary",
                                title="log(IC50) vs Binding Probability (Lower log(IC50) = Better)",
                                color="affinity_probability_binary",
                                color_continuous_scale="viridis",
                                labels={
                                    "affinity_pred_value": "log(IC50) Prediction",
                                    "affinity_probability_binary": "Binding Probability"
                                }
                            )
                            st.plotly_chart(fig_scatter, use_container_width=True)
                        else:
                            # Show affinity by round if multiple rounds exist
                            if "round" in affinity_with_values.columns and len(affinity_with_values["round"].unique()) > 1:
                                fig_box_aff = px.box(
                                    affinity_with_values,
                                    x="round",
                                    y="affinity_pred_value",
                                    title="log(IC50) Predictions by Round (Lower = Better)",
                                    color_discrete_sequence=["#48bb78"]
                                )
                                fig_box_aff.update_layout(
                                    xaxis_title="Round",
                                    yaxis_title="log(IC50) Prediction"
                                )
                                st.plotly_chart(fig_box_aff, use_container_width=True)
                            else:
                                # Show affinity statistics
                                st.markdown("**log(IC50) Statistics:**")
                                aff_stats = affinity_with_values["affinity_pred_value"].describe()
                                aff_stats_df = pd.DataFrame({
                                    "Statistic": ["Count", "Mean", "Std", "Min", "25%", "50%", "75%", "Max"],
                                    "Value": [
                                        f"{aff_stats['count']:.0f}",
                                        f"{aff_stats['mean']:.3f}",
                                        f"{aff_stats['std']:.3f}",
                                        f"{aff_stats['min']:.3f}",
                                        f"{aff_stats['25%']:.3f}",
                                        f"{aff_stats['50%']:.3f}",
                                        f"{aff_stats['75%']:.3f}",
                                        f"{aff_stats['max']:.3f}"
                                    ]
                                })
                                st.dataframe(aff_stats_df, use_container_width=True, hide_index=True)
                    
                    # Show top affinity performers (lowest log(IC50) values are best)
                    st.markdown("**🏆 Top 10 log(IC50) Predictions (Lowest/Best Values):**")
                    top_affinity = affinity_with_values.nsmallest(10, "affinity_pred_value")
                    
                    # Add IC50 conversion column for better interpretation
                    top_affinity_display = top_affinity.copy()
                    # Convert log(IC50) to approximate IC50 in μM: IC50 ≈ 10^(log(IC50))
                    top_affinity_display["estimated_IC50_uM"] = 10 ** top_affinity_display["affinity_pred_value"]
                    # Convert to pIC50 in kcal/mol: pIC50 = (6 - log(IC50)) × 1.364
                    top_affinity_display["pIC50_kcal_mol"] = (6 - top_affinity_display["affinity_pred_value"]) * 1.364
                    
                    aff_display_cols = ["compound_id", "affinity_pred_value", "estimated_IC50_uM", "pIC50_kcal_mol", "round"]
                    if "variant_id" in top_affinity_display.columns:
                        aff_display_cols.insert(1, "variant_id")
                    if "barcode" in top_affinity_display.columns:
                        aff_display_cols.insert(2, "barcode")
                    if "affinity_probability_binary" in top_affinity_display.columns:
                        aff_display_cols.insert(-1, "affinity_probability_binary")
                    
                    existing_aff_cols = [col for col in aff_display_cols if col in top_affinity_display.columns]
                    
                    # Format the dataframe for better display
                    display_df = top_affinity_display[existing_aff_cols].copy()
                    if "estimated_IC50_uM" in display_df.columns:
                        display_df["estimated_IC50_uM"] = display_df["estimated_IC50_uM"].apply(lambda x: f"{x:.2e}")
                    if "affinity_pred_value" in display_df.columns:
                        display_df["affinity_pred_value"] = display_df["affinity_pred_value"].round(3)
                    if "pIC50_kcal_mol" in display_df.columns:
                        display_df["pIC50_kcal_mol"] = display_df["pIC50_kcal_mol"].round(3)
                    if "affinity_probability_binary" in display_df.columns:
                        display_df["affinity_probability_binary"] = display_df["affinity_probability_binary"].round(3)
                    
                    st.dataframe(
                        display_df,
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    st.caption("💡 estimated_IC50_uM = 10^(log(IC50)); pIC50_kcal_mol = (6 - log(IC50)) × 1.364")

            # Docking score distribution if available
            if "docking_score" in df.columns and df["docking_score"].notna().any():
                st.subheader("🎯 Docking Score Analysis")
                
                docked_with_scores = df[df["docking_score"].notna()]
                if not docked_with_scores.empty:
                    # Create two columns for different visualizations
                    viz_col1, viz_col2 = st.columns(2)
                    
                    with viz_col1:
                        # Histogram of docking scores
                        fig_hist = px.histogram(
                            docked_with_scores,
                            x="docking_score",
                            nbins=20,
                            title="Distribution of Docking Scores",
                            color_discrete_sequence=["#63b3ed"],
                            labels={"docking_score": "Docking Score", "count": "Number of Compounds"}
                        )
                        fig_hist.update_layout(bargap=0.1)
                        st.plotly_chart(fig_hist, use_container_width=True)
                    
                    with viz_col2:
                        # Box plot by round if multiple rounds exist
                        if "round" in docked_with_scores.columns and len(docked_with_scores["round"].unique()) > 1:
                            fig_box = px.box(
                                docked_with_scores,
                                x="round",
                                y="docking_score",
                                title="Docking Scores by Round",
                                color_discrete_sequence=["#f56565"]
                            )
                            fig_box.update_layout(
                                xaxis_title="Round",
                                yaxis_title="Docking Score"
                            )
                            st.plotly_chart(fig_box, use_container_width=True)
                        else:
                            # Show summary statistics instead
                            st.markdown("**Summary Statistics:**")
                            stats = docked_with_scores["docking_score"].describe()
                            stats_df = pd.DataFrame({
                                "Statistic": ["Count", "Mean", "Std", "Min", "25%", "50%", "75%", "Max"],
                                "Value": [
                                    f"{stats['count']:.0f}",
                                    f"{stats['mean']:.2f}",
                                    f"{stats['std']:.2f}",
                                    f"{stats['min']:.2f}",
                                    f"{stats['25%']:.2f}",
                                    f"{stats['50%']:.2f}",
                                    f"{stats['75%']:.2f}",
                                    f"{stats['max']:.2f}"
                                ]
                            })
                            st.dataframe(stats_df, use_container_width=True, hide_index=True)
                
                # Show top performers (lowest/best scores)
                st.markdown("**🏆 Top 10 Docking Performers (Lowest/Best Scores):**")
                top_performers = docked_with_scores.nsmallest(10, "docking_score")
                display_cols = ["compound_id", "docking_score", "round"]
                if "variant_id" in top_performers.columns:
                    display_cols.insert(1, "variant_id")
                if "barcode" in top_performers.columns:
                    display_cols.insert(2, "barcode")
                
                existing_cols = [col for col in display_cols if col in top_performers.columns]
                st.dataframe(
                    top_performers[existing_cols],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No compounds with docking scores are available yet.")
                
            # Combined Analysis Section - Show correlation if both affinity and docking data exist
            if ("affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any() and
                "docking_score" in df.columns and df["docking_score"].notna().any()):
                
                st.subheader("🔬 Combined Affinity vs Docking Analysis")
                
                # Get compounds that have both affinity and docking data
                combined_data = df[
                    df["affinity_pred_value"].notna() & 
                    df["docking_score"].notna()
                ]
                
                if not combined_data.empty:
                    # Create correlation plot
                    fig_corr = px.scatter(
                        combined_data,
                        x="docking_score",
                        y="affinity_pred_value",
                        color="affinity_probability_binary" if "affinity_probability_binary" in combined_data.columns else None,
                        title="Docking Score vs log(IC50) Prediction (Both Lower = Better)",
                        hover_data=["compound_id", "barcode"] if "barcode" in combined_data.columns else ["compound_id"],
                        labels={
                            "docking_score": "Docking Score (lower=better)",
                            "affinity_pred_value": "log(IC50) Prediction (lower=better)",
                            "affinity_probability_binary": "Binding Probability"
                        }
                    )
                    st.plotly_chart(fig_corr, use_container_width=True)
                    
                    # Show correlation coefficient
                    correlation = combined_data["docking_score"].corr(combined_data["affinity_pred_value"])
                    st.info(f"Correlation between docking score and log(IC50): {correlation:.3f} (positive correlation means both values tend to move together)")
                    
                    # Show top combined performers
                    st.markdown("**🎯 Best Combined Performance (Low log(IC50) + Low Docking Score):**")
                    # Normalize scores for ranking (lower values are better for both)
                    combined_data_normalized = combined_data.copy()
                    combined_data_normalized["docking_score_norm"] = (
                        (combined_data["docking_score"].max() - combined_data["docking_score"]) / 
                        (combined_data["docking_score"].max() - combined_data["docking_score"].min())
                    )
                    combined_data_normalized["affinity_norm"] = (
                        (combined_data["affinity_pred_value"].max() - combined_data["affinity_pred_value"]) / 
                        (combined_data["affinity_pred_value"].max() - combined_data["affinity_pred_value"].min())
                    )
                    combined_data_normalized["combined_score"] = (
                        combined_data_normalized["docking_score_norm"] + 
                        combined_data_normalized["affinity_norm"]
                    ) / 2
                    
                    # Add estimated IC50 for better interpretation
                    combined_data_normalized["estimated_IC50_uM"] = 10 ** combined_data_normalized["affinity_pred_value"]
                    
                    top_combined = combined_data_normalized.nlargest(10, "combined_score")
                    combined_display_cols = ["compound_id", "docking_score", "affinity_pred_value", "estimated_IC50_uM", "combined_score"]
                    if "variant_id" in top_combined.columns:
                        combined_display_cols.insert(1, "variant_id")
                    if "barcode" in top_combined.columns:
                        combined_display_cols.insert(2, "barcode")
                    if "affinity_probability_binary" in top_combined.columns:
                        combined_display_cols.insert(-1, "affinity_probability_binary")
                    
                    existing_combined_cols = [col for col in combined_display_cols if col in top_combined.columns]
                    
                    # Format the display
                    display_combined = top_combined[existing_combined_cols].copy()
                    if "estimated_IC50_uM" in display_combined.columns:
                        display_combined["estimated_IC50_uM"] = display_combined["estimated_IC50_uM"].apply(lambda x: f"{x:.2e}")
                    
                    st.dataframe(
                        display_combined.round(3),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.info("No compounds have both affinity and docking data for correlation analysis.")

        elif st.session_state.selected_view == "Compounds":
            st.header("Generated Compounds")
            
            # Check if we have any compounds at all
            if "status" not in df.columns or not any(status for status in df["status"].unique() if status == "GENERATED"):
                st.info("No compounds have been generated yet. This tab will populate when compound generation completes.")
            else:
                # Enhanced filter controls
                filter_col1, filter_col2, filter_col3 = st.columns([2, 1, 1])
                with filter_col1:
                    round_options_compounds = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds = st.multiselect(
                        "Filter by Round",
                        options=round_options_compounds,
                        default=round_options_compounds,
                        key="compounds_rounds"
                    )
                with filter_col2:
                    sort_options = ["compound_id", "generation"]
                    if "round" in df.columns:
                        sort_options.insert(1, "round")
                    
                    sort_by = st.selectbox(
                        "Sort by",
                        options=sort_options,
                        index=0,
                        key="compounds_sort"
                    )
                with filter_col3:
                    sort_order = st.radio(
                        "Order",
                        options=["Ascending", "Descending"],
                        horizontal=True,
                        key="compounds_order"
                    )
                
                # Filter and sort compounds
                try:
                    # First filter by status
                    compounds_df = df[df["status"] == "GENERATED"]
                    
                    # Then apply round filter if selected
                    if selected_rounds:
                        compounds_df = compounds_df[compounds_df["round"].isin(selected_rounds)]
                    
                    # Apply sorting if the column exists
                    if sort_by in compounds_df.columns:
                        ascending = sort_order == "Ascending"
                        compounds_df = compounds_df.sort_values(sort_by, ascending=ascending)
                except Exception as e:
                    st.error(f"Error filtering compounds: {e}")
                    compounds_df = pd.DataFrame()
                
                # Display count
                st.info(f"Displaying {len(compounds_df)} compounds")
                
                if compounds_df.empty:
                    st.warning("No compounds match the current filter criteria. Try adjusting the filters.")
                else:
                    # Determine which columns to display
                    display_columns = ["compound_id"]
                    if "barcode" in compounds_df.columns:
                        display_columns.append("barcode")
                    if "round" in compounds_df.columns:
                        display_columns.append("round")
                    if "generation" in compounds_df.columns:
                        display_columns.append("generation")
                    display_columns.append("smiles")
                    
                    # Only include columns that exist
                    existing_columns = [col for col in display_columns if col in compounds_df.columns]
                    
                    # First show the dataframe
                    st.dataframe(
                        compounds_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    if not compounds_df.empty:
                        st.download_button(
                            "Download Filtered Compounds",
                            data=compounds_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_compounds.csv",
                            mime="text/csv"
                        )
                        
        elif st.session_state.selected_view == "Variants":
            st.header("Synthesized Variants")
            
            # Check if we have any variants at all
            if "status" in df.columns and not any(status for status in df["status"].unique() if status in ["SYNTHETIZED", "PASSFILTER", "PASSBLINDDOCK"]):
                st.info("No variants have been synthesized yet. This tab will populate when retrosynthesis completes.")
                
                # Show what stages have been reached
                available_statuses = df["status"].unique() if "status" in df.columns else []
                if "GENERATED" in available_statuses:
                    st.success("✅ Compounds have been generated")
                    st.info("⏳ Waiting for retrosynthesis to complete")
            else:
                # Enhanced filter controls
                filter_col1, filter_col2, filter_col3 = st.columns(3)
                with filter_col1:
                    status_options = sorted([
                        s
                        for s in df["status"].unique()
                        if pd.notna(s)
                        and s
                        in [
                            "SYNTHETIZED",
                            "PASSFILTER",
                            "PASSBLINDDOCK",
                            "DOCKED",
                        ]
                    ])
                    default_status = [s for s in status_options if s in ["SYNTHETIZED", "PASSFILTER"]]
                    selected_status = st.multiselect(
                        "Filter by Status",
                        options=status_options,
                        default=default_status if default_status else status_options,
                        key="variants_status"
                    )
                with filter_col2:
                    round_options_var = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds_var = st.multiselect(
                        "Filter by Round",
                        options=round_options_var,
                        default=round_options_var,
                        key="variants_rounds"
                    )
                with filter_col3:
                    if "score" in df.columns and df["score"].notna().any():
                        valid_scores = df["score"].dropna()
                        if not valid_scores.empty:
                            min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                        else:
                            min_score, max_score = 0.0, 1.0
                            
                        score_range = st.slider(
                            "Score Range",
                            min_value=min_score,
                            max_value=max_score,
                            value=(min_score, max_score),
                            key="variants_score"
                        )
                        score_filter = (df["score"] >= score_range[0]) & (df["score"] <= score_range[1])
                    else:
                        score_filter = pd.Series(True, index=df.index)
                        if "score" not in df.columns:
                            st.info("No score data available in variants")
                
                # Add sorting options
                sort_col1, sort_col2 = st.columns(2)
                with sort_col1:
                    sort_options = ["variant_id", "round", "generation"]
                    if "score" in df.columns:
                        sort_options.append("score")
                        
                    sort_by_var = st.selectbox(
                        "Sort by",
                        options=sort_options,
                        index=0,
                        key="variants_sort"
                    )
                with sort_col2:
                    sort_order_var = st.radio(
                        "Order",
                        options=["Ascending", "Descending"],
                        horizontal=True,
                        key="variants_order"
                    )
                
                # Filter and display variants
                try:
                    if selected_status and selected_rounds_var:
                        variants_df = df[
                            (df["status"].isin(selected_status)) &
                            (df["round"].isin(selected_rounds_var))
                        ]
                        # Apply score filter if it exists
                        if "score" in df.columns:
                            variants_df = variants_df[score_filter]
                            
                        # Sort values if possible
                        if sort_by_var in variants_df.columns:
                            ascending_var = sort_order_var == "Ascending"
                            variants_df = variants_df.sort_values(sort_by_var, ascending=ascending_var)
                    else:
                        variants_df = pd.DataFrame()
                except Exception as e:
                    st.error(f"Error filtering variants: {e}")
                    variants_df = pd.DataFrame()
                
                # Display count
                st.info(f"Displaying {len(variants_df)} variants")
                
                if variants_df.empty:
                    st.warning("No variants match the current filter criteria. Try adjusting the filters.")
                else:
                    # Show the dataframe with columns that exist
                    display_columns = ["variant_id", "round", "generation", "status", "smiles"]
                    if "parent_id" in variants_df.columns:
                        display_columns.insert(1, "parent_id")
                    if "score" in variants_df.columns:
                        display_columns.insert(-1, "score")
                    
                    # Only include columns that exist
                    existing_columns = [col for col in display_columns if col in variants_df.columns]
                    
                    st.dataframe(
                        variants_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    if not variants_df.empty:
                        st.download_button(
                            "Download Filtered Variants",
                            data=variants_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_variants.csv",
                            mime="text/csv"
                        )
                        
        elif st.session_state.selected_view == "Docking Results":
            st.header("Docking Results")
            
            if "docking_score" not in df.columns or df["docking_score"].notna().sum() == 0:
                st.info("No docking scores available in the tracking report yet. This tab will populate when docking completes.")
                
                # Show what stages have been reached
                if "status" in df.columns:
                    available_statuses = df["status"].unique()
                    if "GENERATED" in available_statuses:
                        st.success("✅ Compounds have been generated")
                    if "SYNTHETIZED" in available_statuses:
                        st.success("✅ Variants have been synthesized")
                    if "PASSFILTER" in available_statuses:
                        st.success("✅ Variants have been filtered")
                    if "DOCKED" not in available_statuses:
                        st.warning("⏳ Docking has not yet completed")
            else:
                # Enhanced filter controls for docking
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    round_options_dock = sorted([r for r in df["round"].unique() if pd.notna(r)])
                    selected_rounds_dock = st.multiselect(
                        "Filter by Round",
                        options=round_options_dock,
                        default=round_options_dock,
                        key="docking_rounds"
                    )
                with filter_col2:
                    valid_scores = df["docking_score"].dropna()
                    if valid_scores.empty:
                        st.info("No valid docking scores found to create a filter range.")
                        score_min_filter = score_max_filter = 0.0
                        score_range_dock = None
                    else:
                        min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                        if min_score == max_score:
                            st.info(f"All filtered compounds have a docking score of {min_score:.2f}.")
                            score_min_filter = score_max_filter = min_score
                            score_range_dock = None
                        else:
                            score_range_dock = st.slider(
                                "Docking Score Range",
                                min_value=min_score,
                                max_value=max_score,
                                value=(min_score, max_score),
                                key="docking_score_range",
                            )
                            score_min_filter, score_max_filter = score_range_dock

                # Filter docked compounds
                try:
                    # Base filter for status and round
                    docked_df = df[
                        (df["status"] == "DOCKED") &
                        (df["round"].isin(selected_rounds_dock))
                    ]
                    # Apply score filter only if there are valid scores
                    if not valid_scores.empty:
                         docked_df = docked_df[
                             (docked_df["docking_score"] >= score_min_filter) &
                             (docked_df["docking_score"] <= score_max_filter)
                         ]
                     
                    # Sort the final filtered df
                    docked_df = docked_df.sort_values("docking_score")

                except Exception as e:
                    st.error(f"Error filtering docked compounds: {e}")
                
                if docked_df.empty:
                    st.info("No docked compounds match the current filter criteria.")
                else:
                    # Docking statistics (lower scores are better)
                    stats_cols = st.columns(4)
                    with stats_cols[0]:
                        st.metric("Best Score (lower=better)", f"{docked_df['docking_score'].min():.2f}")
                    with stats_cols[1]:
                        st.metric("Average Score", f"{docked_df['docking_score'].mean():.2f}")
                    with stats_cols[2]:
                        st.metric("Median Score", f"{docked_df['docking_score'].median():.2f}")
                    with stats_cols[3]:
                        st.metric("Total Docked", len(docked_df))
                        
                    # Score distribution
                    st.subheader("Score Distribution (Lower = Better)")
                    try:
                        fig = px.scatter(
                            docked_df,
                            x="round",
                            y="docking_score",
                            color="docking_score",
                            hover_data=["compound_id", "smiles"],
                            title="Docking Scores by Round (Lower = Better)",
                            color_continuous_scale="viridis_r",  # Reverse scale so lower values are brighter
                            labels={"docking_score": "Docking Score (lower=better)"}
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    except Exception as e:
                        st.error(f"Error creating score distribution plot: {e}")
                    
                    # Full docking results table
                    st.subheader("All Docking Results")
                    # Ensure required columns exist
                    table_columns = ["compound_id", "round", "docking_score", "status", "smiles"]
                    if "variant_id" in docked_df.columns:
                        table_columns.insert(1, "variant_id")
                    if "barcode" in docked_df.columns:
                        table_columns.insert(2, "barcode")
                    if "pose_count" in docked_df.columns:
                        table_columns.insert(-1, "pose_count")
                    if "all_scores" in docked_df.columns:
                        table_columns.insert(-1, "all_scores")
                        
                    # Only include columns that exist
                    existing_columns = [col for col in table_columns if col in docked_df.columns]
                    
                    st.dataframe(
                        docked_df[existing_columns],
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    # Add download button for this filtered view
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            "Download Filtered Docking Results",
                            data=docked_df.to_csv(index=False).encode('utf-8'),
                            file_name="filtered_docking_results.csv",
                            mime="text/csv"
                        )
                    with col2:
                        # Add option to view 3D structures for selected compounds
                        if st.button("🧬 View 3D Structures", help="View 3D molecular structures for top results"):
                            st.session_state.show_3d_structures = True

                    # 3D Structure Viewer Section
                    if st.session_state.get('show_3d_structures', False):
                        st.subheader("🧬 3D Molecular Structures")
                        
                        # Allow user to select which compounds to visualize
                        st.markdown("Select compounds to visualize in 3D:")
                        
                        # Create a selection interface
                        top_10_results = docked_df.head(10)
                        
                        selected_indices = []
                        for idx, result in top_10_results.iterrows():
                            variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                            score = result.get('docking_score', 0)
                            
                            if st.checkbox(f"{variant_id} (Score: {score:.2f})", key=f"3d_select_{variant_id}"):
                                selected_indices.append(idx)
                        
                        # Display 3D structures for selected compounds
                        if selected_indices:
                            for idx in selected_indices:
                                result = docked_df.loc[idx]
                                variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                                
                                st.markdown(f"### 🎯 {variant_id}")
                                create_interactive_3d_viewer(result, st.session_state.output_dir)
                                st.divider()
                        else:
                            st.info("Select compounds above to view their 3D structures")
                        
                        # Add button to hide 3D structures
                        if st.button("Hide 3D Structures"):
                            st.session_state.show_3d_structures = False
                            st.rerun()
                    
                    # Detailed docking results with 3D visualization
                    st.subheader("Top Docking Results with 3D Visualization")
                    
                    # Show top 5 results with detailed information
                    top_results = docked_df.head(5)
                    
                    for idx, result in top_results.iterrows():
                        variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                        barcode = result.get('barcode', 'Unknown')
                        
                        with st.expander(f"🏆 {variant_id} - Score: {result.get('docking_score', 0):.2f}"):
                            col1, col2 = st.columns([1, 2])
                            
                            with col1:
                                # Render 2D structure
                                if "smiles" in result and not pd.isna(result["smiles"]):
                                    mol_img = render_mol(result["smiles"])
                                    if mol_img:
                                        st.image(mol_img, caption="2D Structure", width=200)
                                
                                # Show Boltz-2 affinity predictions
                                if "affinity_pred_value" in result and not pd.isna(result["affinity_pred_value"]):
                                    st.markdown("**🤖 Boltz-2 Predictions:**")
                                    log_ic50 = result['affinity_pred_value']
                                    estimated_ic50 = 10 ** log_ic50
                                    pic50_kcal_mol = (6 - log_ic50) * 1.364
                                    
                                    affinity_data = {
                                        "log(IC50)": f"{log_ic50:.3f}",
                                        "Estimated IC50": f"{estimated_ic50:.2e} μM",
                                        "pIC50": f"{pic50_kcal_mol:.3f} kcal/mol",
                                    }
                                    if "affinity_probability_binary" in result and not pd.isna(result["affinity_probability_binary"]):
                                        prob_val = result["affinity_probability_binary"]
                                        confidence_text = "Predicted Binder" if prob_val > 0.5 else "Predicted Non-Binder"
                                        affinity_data["Binding Probability"] = f"{prob_val:.3f} ({confidence_text})"
                                    
                                    for key, value in affinity_data.items():
                                        st.write(f"**{key}:** {value}")
                                    
                                    # Add interpretation
                                    if log_ic50 < -1:
                                        interpretation = "🟢 Strong Binder"
                                    elif log_ic50 < 1:
                                        interpretation = "🟡 Moderate Binder"
                                    else:
                                        interpretation = "🔴 Weak Binder/Decoy"
                                    st.write(f"**Interpretation:** {interpretation}")
                                    
                                    st.divider()
                                
                                # Show docking statistics
                                st.markdown("**🎯 Docking Statistics:**")
                                stats_data = {
                                    "Score": f"{result.get('docking_score', 'N/A'):.2f}" if pd.notna(result.get('docking_score')) else "N/A",
                                    "Poses": result.get('pose_count', 'N/A'),
                                    "Round": result.get('round', 'N/A'),
                                    "Status": result.get('status', 'N/A')
                                }
                                
                                if "all_scores" in result and not pd.isna(result["all_scores"]):
                                    try:
                                        # Parse all_scores if it's a string representation of a list
                                        all_scores_str = str(result["all_scores"])
                                        if all_scores_str.startswith('[') and all_scores_str.endswith(']'):
                                            import ast
                                            all_scores = ast.literal_eval(all_scores_str)
                                            if len(all_scores) > 1:
                                                stats_data["Score Range"] = f"{min(all_scores):.2f} to {max(all_scores):.2f}"
                                    except:
                                        pass
                                
                                for key, value in stats_data.items():
                                    st.write(f"**{key}:** {value}")
                            
                            with col2:
                                # Create comprehensive 3D visualization
                                create_interactive_3d_viewer(result, st.session_state.output_dir)
    
    # Enhanced Export options
    st.divider()
    st.markdown("## 💾 Export & Download Options")
    st.markdown("Export your analyzed data for external analysis or sharing")

    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        if st.button("Export All Results"):
            st.download_button(
                "📥 Download Complete Dataset",
                data=df.to_csv(index=False).encode('utf-8'),
                file_name="all_results.csv",
                mime="text/csv"
            )

    with export_col2:
        if (st.button("Export Docking Results") 
            and "docking_score" in df.columns):
            
            docked_df = df[df["status"] == "DOCKED"]
            st.download_button(
                "📥 Download Docking Results",
                data=docked_df.to_csv(index=False).encode('utf-8'),
                file_name="docking_results.csv",
                mime="text/csv"
            )

    with export_col3:
        if st.button("Export Summary Statistics"):
            stats = {
                "total_compounds": len(df[df["status"] == "GENERATED"]),
                "total_variants": len(df[df["status"] == "SYNTHETIZED"]),
                "filtered_variants": len(df[df["status"] == "PASSFILTER"]),
                "docked_compounds": len(df[df["status"] == "DOCKED"]),
                }
            
            if "docking_score" in df.columns and df["docking_score"].notna().any():
                stats["average_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].mean())
                stats["best_docking_score"] = float(df[df["docking_score"].notna()]["docking_score"].min())
            
            if "affinity_pred_value" in df.columns and df["affinity_pred_value"].notna().any():
                stats["average_log_ic50"] = float(df[df["affinity_pred_value"].notna()]["affinity_pred_value"].mean())
                stats["best_log_ic50"] = float(df[df["affinity_pred_value"].notna()]["affinity_pred_value"].min())  # Lower is better
                if "affinity_probability_binary" in df.columns:
                    predicted_binders = len(df[df["affinity_probability_binary"] > 0.5])
                    stats["predicted_binders"] = predicted_binders
            
            st.json(stats)

    # Dashboard footer
    st.divider()
    st.markdown("""
        <div style="text-align: center; padding: 2rem; background: #f8f9fa; border-radius: 10px; margin: 2rem 0;">
            <p style="margin: 0; color: #6c757d;">
                <strong>Visualize Pipeline Results</strong> | Comprehensive exploration and analysis<br>
                🔄 Interactive visualizations | 📊 Advanced analytics | 🧬 3D molecular viewers
            </p>
        </div>
    """, unsafe_allow_html=True)
else:
    # No results data available
    st.info("Please select an output directory and load results to view visualizations.")
    
    # Show help information when no data is loaded
    st.markdown("### 💡 Getting Started")
    st.markdown("""
    **To start visualizing your pipeline results:**
    
    1. **Enter the output directory path** in the text field above
    2. **Wait for automatic loading** of the tracking report
    3. **Explore different views** using the sidebar navigation
    
    **Supported Directory Structures:**
    - Pipeline output directories with `master_tracking/` folder
    - Round-specific directories with `round_*/` folders
    - Directories containing tracking reports (CSV files)
    
    **Features Available:**
    - 📊 Summary dashboard with key metrics
    - 🧬 Compound and variant exploration
    - 🎯 Docking results with 3D visualization
    - 🤖 Boltz-2 affinity predictions analysis
    - 💾 Export and download capabilities
    """) 