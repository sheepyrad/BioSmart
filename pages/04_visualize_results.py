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
                    '<div style="text-align:center; padding:50px; color:red;">' +
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
    page_title="Results Analysis",
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
    </style>
""", unsafe_allow_html=True)

# Header for analysis page
st.markdown("""
    <div class="analysis-header">
        <h1>🔍 Pipeline Results Analysis <span class="analysis-indicator">📈</span></h1>
        <p>Comprehensive post-hoc analysis of completed pipeline runs</p>
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

st.info("Enter the path to any completed pipeline output directory for analysis")

# Enter path manually
dir_path = st.text_input(
    "Output Directory Path:", 
    placeholder="/path/to/outputs/pipeline_run_name",
    help="Enter the full path to a pipeline output directory containing results to analyze"
)

# Process manually entered path
if dir_path:
    output_dir_path = Path(dir_path)
    if output_dir_path.exists() and output_dir_path.is_dir():
        st.success(f"✅ Directory Found: {output_dir_path}")
        st.session_state.output_dir = output_dir_path
    else:
        st.error(f"❌ Directory not found: {output_dir_path}")
        st.session_state.output_dir = None

# Load results if directory is available
if st.session_state.output_dir:
    st.info(f"📊 Ready to analyze: {st.session_state.output_dir.name}")
    
    if st.button("🔬 Load & Analyze Results", type="primary"):
        with st.spinner("🔄 Loading and processing results data..."):
            try:
                results = load_results(st.session_state.output_dir)
                if results is None:
                    st.error("❌ Failed to load results - check if the directory contains valid pipeline output")
                else:
                    st.session_state.results_data = results
                    st.balloons()
                    st.success("✅ Successfully loaded results! Analysis dashboard is now available.")
            except Exception as e:
                st.error(f"❌ Error processing results: {str(e)}")
                import traceback
                st.code(traceback.format_exc())
else:
    st.warning("📁 Please enter a valid pipeline output directory path above to start your analysis.")
    st.info("💡 **Tip:** Look for directories containing 'master_tracking' or 'round_*' subdirectories.")

# Navigation
if st.session_state.results_data:
    # Enhanced Sidebar for navigation
    with st.sidebar:
        st.markdown("""
            <div style="text-align: center; padding: 1rem; background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); border-radius: 10px; color: white; margin-bottom: 1rem;">
                <h3>📊 ANALYSIS MODE</h3>
                <p style="margin: 0; font-size: 0.9em;">Post-hoc exploration</p>
            </div>
        """, unsafe_allow_html=True)
        
        st.session_state.selected_view = st.radio(
            "🔬 Analysis Views",
            ["Summary", "Compounds", "Variants", "Docking Results"],
            help="Select different analysis perspectives of your data"
        )
        
        st.divider()
        
        # Global Receptor File Configuration
        st.subheader("🔬 Global Receptor File")
        global_receptor_path = st.text_input(
            "Receptor File Path",
            placeholder="Enter path to receptor file (.pdbqt or .pdb)",
            help="Set a global receptor file path to use for all 3D visualizations on this page",
            key="global_receptor_path"
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
        df = st.session_state.results_data["tracking_report"]
        
        # Round filter (applies to all views)
        # Filter out NaN values from options
        round_options = sorted([r for r in df["round"].unique() if pd.notna(r)])
        sidebar_rounds = st.multiselect(
            "Filter by Round",
            options=round_options,
            default=round_options,
            key="sidebar_rounds"
        )
        
        # Status filter
        status_options = sorted([s for s in df["status"].unique() if pd.notna(s)])
        sidebar_status = st.multiselect(
            "Filter by Status",
            options=status_options,
            default=status_options,
            key="sidebar_status"
        )
        
        # Apply global filters
        if sidebar_rounds and sidebar_status:
            filtered_df = df[df["round"].isin(sidebar_rounds) & df["status"].isin(sidebar_status)]
        else:
            filtered_df = df
            
    # Main content based on selected view
    if st.session_state.selected_view == "Summary":
        st.markdown("## 📊 Pipeline Results Analysis")
        
        # Determine what pipeline stages have been reached
        available_statuses = df["status"].unique() if "status" in df.columns else []
        
        # Enhanced Summary metrics with styling
        st.markdown("### 🔢 Key Metrics")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            compound_count = len(df[df["status"] == "GENERATED"]) if "status" in df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🧬 Compounds</h4>
                    <h2 style="color: #11998e; margin: 0;">{compound_count}</h2>
                    <small>Generated</small>
                </div>
            """, unsafe_allow_html=True)
        with col2:
            variant_count = len(df[df["status"] == "SYNTHETIZED"]) if "status" in df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>⚗️ Variants</h4>
                    <h2 style="color: #11998e; margin: 0;">{variant_count}</h2>
                    <small>Synthesized</small>
                </div>
            """, unsafe_allow_html=True)
        with col3:
            filtered_count = len(df[df["status"].isin(["PASSFILTER", "PASSBLINDDOCK"])]) if "status" in df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🔬 Filtered</h4>
                    <h2 style="color: #11998e; margin: 0;">{filtered_count}</h2>
                    <small>Passed filters</small>
                </div>
            """, unsafe_allow_html=True)
        with col4:
            docked_count = len(df[df["status"] == "DOCKED"]) if "status" in df.columns else 0
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🎯 Docked</h4>
                    <h2 style="color: #11998e; margin: 0;">{docked_count}</h2>
                    <small>Completed</small>
                </div>
            """, unsafe_allow_html=True)
        with col5:
            # Show best docking score if available
            if "docking_score" in df.columns and df["docking_score"].notna().any():
                best_score = df[df["docking_score"].notna()]["docking_score"].min()
                score_text = f"{best_score:.2f}"
            else:
                score_text = "N/A"
            st.markdown(f"""
                <div class="metric-container">
                    <h4>🏆 Best Score</h4>
                    <h2 style="color: #11998e; margin: 0;">{score_text}</h2>
                    <small>Lower = better</small>
                </div>
            """, unsafe_allow_html=True)
        
        # Show pipeline progress information
        progress_message = ""
        if "GENERATED" in available_statuses and "SYNTHETIZED" not in available_statuses:
            progress_message = "Pipeline has generated compounds but not yet completed retrosynthesis."
        elif "SYNTHETIZED" in available_statuses and "PASSFILTER" not in available_statuses:
            progress_message = "Pipeline has generated variants but not yet completed filtering."
        elif "PASSFILTER" in available_statuses and "DOCKED" not in available_statuses:
            progress_message = "Pipeline has filtered variants but not yet completed docking."
        
        if progress_message:
            st.info(progress_message + " Some visualizations may not be available until those steps complete.")
        
        # Docking score distribution if available
        if "docking_score" in df.columns and df["docking_score"].notna().any():
            st.subheader("Docking Score Distribution")
            
            # Just show regular histogram if only one type exists or if data is available
            docked_with_scores = df[df["docking_score"].notna()]
            if not docked_with_scores.empty:
                fig = px.histogram(
                    docked_with_scores,
                    x="docking_score",
                    nbins=20,
                    title="Distribution of Docking Scores",
                    color_discrete_sequence=["#4287f5"]
                )
                fig.update_layout(bargap=0.1)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No compounds with docking scores are available yet.")
        else:
            st.info("No docking scores available in the tracking report. This section will populate when docking completes.")
    
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
                
                # Then show expandable elements with molecule renderings
                st.subheader("Compound Structures")
                
                # Add pagination for large datasets
                if len(compounds_df) > 10:
                    compounds_per_page = st.slider("Compounds per page", 5, 20, 10, key="compounds_per_page")
                    page_number = st.number_input("Page", min_value=1, max_value=max(1, len(compounds_df) // compounds_per_page + 1), step=1, key="compounds_page")
                    start_idx = (page_number - 1) * compounds_per_page
                    end_idx = min(start_idx + compounds_per_page, len(compounds_df))
                    paginated_df = compounds_df.iloc[start_idx:end_idx]
                else:
                    paginated_df = compounds_df
                
                for _, compound in paginated_df.iterrows():
                    with st.expander(f"Compound {compound.get('compound_id', 'Unknown')}"):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Display 2D structure
                            if "smiles" in compound and not pd.isna(compound["smiles"]):
                                mol_img = render_mol(compound["smiles"])
                                if mol_img:
                                    st.image(mol_img, caption="2D Structure", width=200)
                                else:
                                    st.info("Could not render molecule structure")
                            else:
                                st.warning("No SMILES data available for this compound")
                        
                        with col2:
                            # Compound details
                            details_tab, variants_tab = st.tabs(["Details", "Related Variants"])
                            
                            with details_tab:
                                # Build details dict with only non-NA values
                                details = {}
                                for field in ["compound_id", "barcode", "generation", "round", "smiles", "source", "timestamp"]:
                                    if field in compound and not pd.isna(compound[field]):
                                        details[field.replace("_", " ").title()] = compound[field]
                                st.json(details)
                            
                            with variants_tab:
                                # Find related variants
                                if "parent_id" in df.columns:
                                    compound_id = compound.get("compound_id", "")
                                    if compound_id:
                                        related_variants = df[df["parent_id"] == compound_id]
                                        
                                        if not related_variants.empty:
                                            # Determine what fields to show in the related variants table
                                            variant_columns = ["variant_id", "status"]
                                            if "score" in related_variants.columns:
                                                variant_columns.append("score")
                                            if "docking_score" in related_variants.columns:
                                                variant_columns.append("docking_score")
                                                
                                            # Only use columns that exist
                                            existing_var_columns = [col for col in variant_columns if col in related_variants.columns]
                                            
                                            st.dataframe(
                                                related_variants[existing_var_columns],
                                                use_container_width=True,
                                                hide_index=True
                                            )
                                            
                                            # Add helpful status information
                                            variant_statuses = related_variants["status"].unique() if "status" in related_variants.columns else []
                                            if "DOCKED" in variant_statuses:
                                                st.success("✅ Some variants have been docked")
                                            elif "PASSFILTER" in variant_statuses:
                                                st.info("⏳ Variants have been filtered but not yet docked")
                                            elif "SYNTHETIZED" in variant_statuses:
                                                st.info("⏳ Variants have been synthesized but not yet filtered or docked")
                                        else:
                                            st.info("No related variants found")
                                    else:
                                        st.info("Compound ID not available to find related variants")
                                else:
                                    st.info("Parent-variant relationship not available")
    
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
                status_options = sorted([s for s in df["status"].unique() if pd.notna(s) and s in ["SYNTHETIZED", "PASSFILTER", "PASSBLINDDOCK", "DOCKED"]])
                default_status = [s for s in status_options if s in ["SYNTHETIZED", "PASSFILTER", "PASSBLINDDOCK"]]
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
                
                # Variant Structures
                st.subheader("Variant Structures")
                
                # Add pagination for large datasets
                if len(variants_df) > 10:
                    variants_per_page = st.slider("Variants per page", 5, 20, 10, key="variants_per_page")
                    page_number = st.number_input("Page", min_value=1, max_value=max(1, len(variants_df) // variants_per_page + 1), step=1, key="variants_page")
                    start_idx = (page_number - 1) * variants_per_page
                    end_idx = min(start_idx + variants_per_page, len(variants_df))
                    paginated_var_df = variants_df.iloc[start_idx:end_idx]
                else:
                    paginated_var_df = variants_df
                
                for _, variant in paginated_var_df.iterrows():
                    with st.expander(f"Variant {variant.get('variant_id', 'Unknown')}"):
                        col1, col2 = st.columns([1, 2])
                        
                        with col1:
                            # Display 2D structure
                            if "smiles" in variant and not pd.isna(variant["smiles"]):
                                mol_img = render_mol(variant["smiles"])
                                if mol_img:
                                    st.image(mol_img, caption="2D Structure", width=200)
                                else:
                                    st.info("Could not render molecule structure")
                            else:
                                st.info("No SMILES data available for this variant")
                            
                            # If parent molecule exists, display it for comparison
                            has_parent_data = "parent_id" in variant and not pd.isna(variant["parent_id"])
                            
                            if has_parent_data:
                                st.subheader("Parent Structure")
                                if "source_smiles" in variant and not pd.isna(variant["source_smiles"]):
                                    parent_mol_img = render_mol(variant["source_smiles"])
                                    if parent_mol_img:
                                        st.image(parent_mol_img, caption="Parent Structure", width=200)
                                    else:
                                        st.info("Could not render parent molecule structure")
                                else:
                                    # Try to find parent SMILES in the dataframe
                                    parent_id = variant.get("parent_id", "")
                                    if parent_id and parent_id in df["compound_id"].values:
                                        parent_smiles = df[df["compound_id"] == parent_id]["smiles"].values[0]
                                        parent_mol_img = render_mol(parent_smiles)
                                        if parent_mol_img:
                                            st.image(parent_mol_img, caption="Parent Structure", width=200)
                                    else:
                                        st.info("Parent structure not available")
                        
                        with col2:
                            # Variant details
                            details = {
                                "Variant ID": variant.get("variant_id", ""),
                                "Status": variant.get("status", ""),
                                "Generation": variant.get("generation", ""),
                                "Round": variant.get("round", ""),
                                "Source": variant.get("source", "")
                            }
                            
                            # Only add optional fields if they exist and are not NA
                            if "parent_id" in variant and not pd.isna(variant["parent_id"]):
                                details["Parent Compound"] = variant["parent_id"]
                            
                            if "timestamp" in variant and not pd.isna(variant["timestamp"]):
                                details["Timestamp"] = variant["timestamp"]
                                
                            if "score" in variant and not pd.isna(variant["score"]):
                                details["Retrosynthesis Score"] = variant["score"]
                                
                            st.json(details)
                            
                            # Link to parent only if parent_id exists and is valid
                            if "parent_id" in variant and not pd.isna(variant["parent_id"]):
                                parent_id = variant.get("parent_id", "")
                                if parent_id and parent_id in df["compound_id"].values:
                                    parent_smiles = df[df["compound_id"] == parent_id]["smiles"].values[0]
                                    st.markdown(f"**Parent SMILES**: `{parent_smiles}`")
                                    
                            # Show docking results if available
                            if variant.get("status") == "DOCKED" and "docking_score" in variant and not pd.isna(variant["docking_score"]):
                                st.success(f"Docking Score: {variant['docking_score']:.2f}")
                                if "best_pose" in variant and not pd.isna(variant["best_pose"]):
                                    st.info(f"Best Pose: {variant['best_pose']}")
    
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
                # Safely get min/max values
                valid_scores = df["docking_score"].dropna() 
                if not valid_scores.empty:
                    min_score, max_score = float(valid_scores.min()), float(valid_scores.max())
                else:
                    min_score, max_score = 0.0, 0.0
                    
                score_range_dock = st.slider(
                    "Docking Score Range",
                    min_value=min_score,
                    max_value=max_score,
                    value=(min_score, max_score),
                    key="docking_score_range"
                )
            
            # Filter docked compounds
            try:
                docked_df = df[
                    (df["status"] == "DOCKED") &
                    (df["round"].isin(selected_rounds_dock)) &
                    (df["docking_score"] >= score_range_dock[0]) &
                    (df["docking_score"] <= score_range_dock[1])
                ].sort_values("docking_score")
            except Exception as e:
                st.error(f"Error filtering docked compounds: {e}")
                docked_df = pd.DataFrame()
            
            if docked_df.empty:
                st.info("No docked compounds match the current filter criteria.")
            else:
                # Docking statistics
                stats_cols = st.columns(4)
                with stats_cols[0]:
                    st.metric("Best Score", f"{docked_df['docking_score'].min():.2f}")
                with stats_cols[1]:
                    st.metric("Average Score", f"{docked_df['docking_score'].mean():.2f}")
                with stats_cols[2]:
                    st.metric("Median Score", f"{docked_df['docking_score'].median():.2f}")
                with stats_cols[3]:
                    st.metric("Total Docked", len(docked_df))
                
                # Score distribution
                st.subheader("Score Distribution")
                try:
                    fig = px.scatter(
                        docked_df,
                        x="round",
                        y="docking_score",
                        color="docking_score",
                        hover_data=["compound_id", "smiles"],
                        title="Docking Scores by Round",
                        color_continuous_scale="viridis"
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
                    
                # Only include columns that exist
                existing_columns = [col for col in table_columns if col in docked_df.columns]
                
                st.dataframe(
                    docked_df[existing_columns],
                    use_container_width=True,
                    hide_index=True
                )
                
                # Add download button and 3D visualization option
                col1, col2 = st.columns(2)
                with col1:
                    st.download_button(
                        "Download Filtered Docking Results",
                        data=docked_df.to_csv(index=False).encode('utf-8'),
                        file_name="filtered_docking_results.csv",
                        mime="text/csv"
                    )
                with col2:
                    if st.button("🧬 View 3D Structures", help="View 3D molecular structures for top results", key="viz_3d_btn"):
                        st.session_state.show_3d_viz = True
                
                # 3D Structure Viewer Section
                if st.session_state.get('show_3d_viz', False):
                    st.subheader("🧬 3D Molecular Structures")
                    
                    # Allow user to select which compounds to visualize
                    st.markdown("Select compounds to visualize in 3D:")
                    
                    # Create a selection interface
                    top_10_results = docked_df.head(10)
                    
                    selected_indices = []
                    for idx, result in top_10_results.iterrows():
                        variant_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                        score = result.get('docking_score', 0)
                        
                        if st.checkbox(f"{variant_id} (Score: {score:.2f})", key=f"viz_3d_select_{variant_id}"):
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
                    if st.button("Hide 3D Structures", key="viz_hide_3d"):
                        st.session_state.show_3d_viz = False
                        st.rerun()
                
                # Top results
                st.subheader("Top Docking Results")
                
                # Add pagination for large datasets
                if len(docked_df) > 10:
                    top_n = st.slider("Show top N results", 5, min(30, len(docked_df)), 10, key="docking_top_n")
                    top_results = docked_df.head(top_n)
                else:
                    top_results = docked_df
                
                for _, result in top_results.iterrows():
                    # Use variant_id if available, otherwise fallback to compound_id
                    display_id = result.get('variant_id', result.get('compound_id', 'Unknown'))
                    
                    with st.expander(f"{display_id} (Score: {result.get('docking_score', 0):.2f})"):
                        # Create tabs for 2D, 3D, and details
                        tab1, tab2, tab3 = st.tabs(["2D Structure", "3D Visualization", "Details"])
                        
                        with tab1:
                            mol_img = render_mol(result["smiles"])
                            if mol_img:
                                st.image(mol_img, caption="2D Structure", width=200)
                            else:
                                st.info("Could not render molecule structure")
                        
                        with tab2:
                            # 3D visualization
                            create_interactive_3d_viewer(result, st.session_state.output_dir)
                        
                        with tab3:
                            # Use .get() for safer access to ensure no KeyError if fields are missing
                            details = {
                                "Compound ID": result.get("compound_id", ""),
                                "Variant ID": result.get("variant_id", ""),
                                "Barcode": result.get("barcode", ""),
                                "Round": result.get("round", ""),
                                "Docking Score": result.get("docking_score", ""),
                                "SMILES": result.get("smiles", "")
                            }
                            
                            # Add Unidock-specific information
                            if "pose_count" in result and not pd.isna(result["pose_count"]):
                                details["Pose Count"] = result["pose_count"]
                            
                            if "all_scores" in result and not pd.isna(result["all_scores"]):
                                try:
                                    # Parse all_scores if it's a string representation of a list
                                    all_scores_str = str(result["all_scores"])
                                    if all_scores_str.startswith('[') and all_scores_str.endswith(']'):
                                        import ast
                                        all_scores = ast.literal_eval(all_scores_str)
                                        if len(all_scores) > 1:
                                            details["Score Range"] = f"{min(all_scores):.2f} to {max(all_scores):.2f}"
                                            details["All Scores"] = all_scores_str
                                except:
                                    pass
                            
                            if "result_file" in result and not pd.isna(result["result_file"]):
                                details["Result File"] = str(Path(result["result_file"]).name)
                            
                            # Only add best_pose if it exists (legacy support)
                            if "best_pose" in result and not pd.isna(result["best_pose"]):
                                details["Best Pose"] = result["best_pose"]
                                
                            st.json(details)
                            
                            # Download options for 3D files
                            if "barcode" in result and not pd.isna(result.get("barcode")) and "round" in result:
                                try:
                                    # Safely handle non-existent directories
                                    variant_dir = Path(st.session_state.output_dir) / f"round_{result['round']}" / "docking_results" / f"variant_{result['barcode']}"
                                    
                                    has_valid_pose = False
                                    pose_file = None
                                    
                                    # Only try to parse best_pose if the field exists
                                    if "best_pose" in result and not pd.isna(result["best_pose"]):
                                        try:
                                            best_pose_num = int(float(result["best_pose"]))
                                            pose_file = variant_dir / f"pose_{best_pose_num}.pdbqt"
                                            if pose_file.exists():
                                                has_valid_pose = True
                                        except (ValueError, TypeError):
                                            # If conversion fails, we'll look for any pose files below
                                            pass
                                    
                                    # Get receptor file path from the input directory
                                    receptor_file = Path(st.session_state.output_dir).parent / "input" / "NS5_test.pdbqt"
                                    
                                    # Check if pose file exists and we can actually read it
                                    if has_valid_pose and pose_file.exists():
                                        try:
                                            with open(pose_file, 'rb') as f:
                                                pose_data = f.read()
                                            
                                            # Download buttons for the best pose and receptor
                                            st.download_button(
                                                "Download Best Pose",
                                                data=pose_data,
                                                file_name=pose_file.name,
                                                mime="application/octet-stream",
                                                key=f"dl_best_pose_{display_id}"
                                            )
                                            
                                            if receptor_file.exists():
                                                with open(receptor_file, 'rb') as f:
                                                    receptor_data = f.read()
                                                
                                                st.download_button(
                                                    "Download Receptor File",
                                                    data=receptor_data,
                                                    file_name=receptor_file.name,
                                                    mime="application/octet-stream",
                                                    key=f"dl_receptor_best_{display_id}"
                                                )
                                        except Exception as e:
                                            st.error(f"Error reading pose file: {e}")
                                    else:
                                        # Try to find all available pose files in the variant directory
                                        if variant_dir.exists():
                                            try:
                                                pose_files = list(variant_dir.glob("pose_*.pdbqt"))
                                                if pose_files:
                                                    st.info(f"Found {len(pose_files)} pose files")
                                                    
                                                    # Extract pose numbers and sort them
                                                    pose_numbers = []
                                                    for p in pose_files:
                                                        try:
                                                            # Extract number from pose_X.pdbqt
                                                            pose_num = int(p.stem.split('_')[1])
                                                            pose_numbers.append((pose_num, p))
                                                        except (ValueError, IndexError):
                                                            continue
                                                    
                                                    if pose_numbers:
                                                        # Sort poses by number
                                                        pose_numbers.sort()
                                                        sorted_poses = [p[1] for p in pose_numbers]
                                                        
                                                        # Create a selection for the poses
                                                        pose_options = [f"Pose {p[0]}" for p in pose_numbers]
                                                        selected_pose_idx = st.selectbox(
                                                            "Select pose", 
                                                            range(len(pose_options)),
                                                            format_func=lambda i: pose_options[i],
                                                            key=f"pose_select_{display_id}"
                                                        )
                                                        
                                                        selected_file = sorted_poses[selected_pose_idx]
                                                        
                                                        try:
                                                            with open(selected_file, 'rb') as f:
                                                                pose_data = f.read()
                                                                
                                                            # Download buttons for the selected pose and receptor
                                                            st.download_button(
                                                                "Download Selected Pose",
                                                                data=pose_data,
                                                                file_name=selected_file.name,
                                                                mime="application/octet-stream",
                                                                key=f"dl_pose_{display_id}"
                                                            )
                                                            
                                                            if receptor_file.exists():
                                                                with open(receptor_file, 'rb') as f:
                                                                    receptor_data = f.read()
                                                                    
                                                                st.download_button(
                                                                    "Download Receptor File",
                                                                    data=receptor_data,
                                                                    file_name=receptor_file.name,
                                                                    mime="application/octet-stream",
                                                                    key=f"dl_receptor_{display_id}"
                                                                )
                                                        except Exception as file_err:
                                                            st.error(f"Error reading pose file: {file_err}")
                                                    else:
                                                        st.info("No valid pose files found")
                                                else:
                                                    st.info(f"No pose files found in {variant_dir}")
                                            except Exception as e:
                                                st.error(f"Error accessing pose files: {e}")
                                        else:
                                            st.info(f"Variant directory not found: {variant_dir}. Docking results may still be processing.")
                                except Exception as e:
                                    st.error(f"Error processing docking results: {e}")
                            else:
                                st.info("Barcode or round information missing for 3D structure visualization")
    
    # Enhanced Export options
    st.divider()
    st.markdown("## 💾 Export & Download Options")
    st.markdown("Export your analyzed data for further research or sharing")
    
    # Add download button for complete dataset
    if st.button("Export All Results"):
        st.download_button(
            "📥 Download Complete Dataset",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name="all_results.csv",
            mime="text/csv"
        )

    # Analysis footer
    st.divider()
    st.markdown("""
        <div style="text-align: center; padding: 2rem; background: #f8f9fa; border-radius: 10px; margin: 2rem 0;">
            <p style="margin: 0; color: #6c757d;">
                <strong>Pipeline Results Analysis</strong> | Comprehensive post-hoc exploration<br>
                📊 Advanced analytics | 🔬 Detailed visualizations | 💾 Flexible export options
            </p>
        </div>
    """, unsafe_allow_html=True)
else:
    st.info("Please select an output directory and load results to view visualizations.") 