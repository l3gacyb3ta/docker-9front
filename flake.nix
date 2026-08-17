{
	inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
	
	outputs = { nixpkgs, ... }:
		let
			system = "x86_64-linux";
			pkgs = import nixpkgs { inherit system; };
		in {
			devShells.${system}.default = pkgs.mkShell {
				packages = with pkgs; [
					qemu
					docker-ls
					docker
					drawterm-wayland
				];

				shellHook = ''
				'';
			};
		};
}
