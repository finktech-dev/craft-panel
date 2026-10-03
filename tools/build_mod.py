import os, sys, shutil, subprocess, zipfile, tempfile

def update_zip_entry(zip_path, file_to_add, arcname):
    if not os.path.exists(zip_path):
        return
    temp_fd, temp_path = tempfile.mkstemp(suffix=".zip")
    os.close(temp_fd)
    
    with zipfile.ZipFile(zip_path, 'r') as zin, zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            if not item.filename.startswith("mods/pointblank_durability") and item.filename != arcname:
                zout.writestr(item, zin.read(item.filename))
        zout.write(file_to_add, arcname)
    
    shutil.move(temp_path, zip_path)

def build():
    print("=== Compiling Point Blank Armory Mod ===")

    project_dir = "pointblank_durability_mod"
    src_dir = os.path.join(project_dir, "src/main/java")
    res_dir = os.path.join(project_dir, "src/main/resources")
    build_dir = os.path.join(project_dir, "build/classes")
    version = "1.1.0"
    dist_jar = os.path.join(project_dir, f"build/pointblank_durability-{version}.jar")
    server_mods_dir = "server/mods"

    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir, exist_ok=True)

    # 1. Collect java files
    java_files = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.endswith(".java"):
                java_files.append(os.path.join(root, f))

    print(f"Found {len(java_files)} Java source files.")

    # 2. Build classpath
    all_libs = []
    for root, dirs, files in os.walk("server/libraries"):
        for f in files:
            if f.endswith(".jar"):
                all_libs.append(os.path.join(root, f))
    for f in os.listdir(server_mods_dir):
        if f.endswith(".jar") and not f.startswith("pointblank_durability"):
            all_libs.append(os.path.join(server_mods_dir, f))

    cp = ";".join(all_libs)

    # 3. Run ECJ compiler
    cmd = ["java", "-jar", "tools/ecj.jar", "-21", "-proc:none", "-cp", cp, "-d", build_dir] + java_files
    print("Running ECJ compiler...")
    res = subprocess.run(cmd, capture_output=True, text=True)

    if res.returncode != 0:
        print("Compilation FAILED!")
        print("Stdout:", res.stdout)
        print("Stderr:", res.stderr)
        sys.exit(1)

    print("Compilation SUCCESSFUL!")
    if res.stderr:
        print("Compiler notes / warnings:\n", res.stderr)

    # 4. Copy resources
    print("Copying resources...")
    for root, dirs, files in os.walk(res_dir):
        rel = os.path.relpath(root, res_dir)
        target_dir = os.path.join(build_dir, rel) if rel != "." else build_dir
        os.makedirs(target_dir, exist_ok=True)
        for f in files:
            src_file = os.path.join(root, f)
            dest_file = os.path.join(target_dir, f)
            shutil.copy2(src_file, dest_file)

    # 5. Package into JAR
    print("Packaging JAR...")
    with zipfile.ZipFile(dist_jar, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(build_dir):
            for f in files:
                full_path = os.path.join(root, f)
                arc_name = os.path.relpath(full_path, build_dir)
                z.write(full_path, arc_name)

    print(f"Generated JAR: {dist_jar} (Size: {os.path.getsize(dist_jar)} bytes)")

    # 6. Deployment is opt-in: ordinary builds must never alter a running server
    # or the client archive merely because a developer wanted a local JAR.
    if "--deploy" in sys.argv:
        for f in os.listdir(server_mods_dir):
            if f.startswith("pointblank_durability") and f.endswith(".jar"):
                try:
                    os.remove(os.path.join(server_mods_dir, f))
                except Exception as e:
                    print(f"Warning cleaning {f}: {e}")
        target_server_jar = os.path.join(server_mods_dir, f"pointblank_durability-{version}.jar")
        shutil.copy2(dist_jar, target_server_jar)
        print(f"Deployed to: {target_server_jar}")

        client_zip = "client_pack/modpack-amigos.zip"
        if os.path.exists(client_zip):
            print(f"Updating mod in client pack: {client_zip}...")
            update_zip_entry(client_zip, dist_jar, f"mods/pointblank_durability-{version}.jar")
            print("Client pack updated cleanly!")

        client_mods_dir = os.path.expandvars(r"%APPDATA%\.minecraft\versions\server\mods")
        if os.path.exists(client_mods_dir):
            for f in os.listdir(client_mods_dir):
                if f.startswith("pointblank_durability") and f.endswith(".jar"):
                    try:
                        os.remove(os.path.join(client_mods_dir, f))
                    except Exception as e:
                        print(f"Warning cleaning {f}: {e}")
            target_client_jar = os.path.join(client_mods_dir, f"pointblank_durability-{version}.jar")
            shutil.copy2(dist_jar, target_client_jar)
            print(f"Deployed to local client: {target_client_jar}")
    else:
        print("JAR packaged only. Use --deploy with the server stopped to copy it to server/mods and client_pack.")

    print("=== Build & Deployment Complete! ===")

if __name__ == "__main__":
    build()
