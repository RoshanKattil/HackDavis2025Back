use anchor_lang::prelude::*;

declare_id!("8ZKteuY8Ro67u6G9ySTmNA1URo9KFjAS6iPoNQKBjrDN");

#[program]
pub mod chain_custody {
    use super::*;

    /// Initialize a new Material record, with the signer as the initial holder.
    pub fn initialize_material(ctx: Context<InitializeMaterial>, material_id: String) -> Result<()> {
        let material_account = &mut ctx.accounts.material_account;
        let initializer = &ctx.accounts.initializer;

        // Set material data
        material_account.current_holder = *initializer.key;
        material_account.last_sequence = 0;
        // Store an ID (truncated/padded to fixed length)
        let id_bytes = material_id.as_bytes();
        let len = id_bytes.len().min(Material::MAX_ID_LEN);
        material_account.id[..len].copy_from_slice(&id_bytes[..len]);
        // Optionally, set an initial status or other fields here
        msg!("Material {} initialized by {}", material_id, initializer.key());
        Ok(())
    }

    /// Transfer custody of a material to a new holder.
    pub fn transfer_material(ctx: Context<TransferMaterial>, new_holder: Pubkey) -> Result<()> {
        let material_account = &mut ctx.accounts.material_account;
        // Current holder must have signed (enforced by `has_one` constraint below)
        let prev_holder = material_account.current_holder;
        material_account.current_holder = new_holder;
        material_account.last_sequence += 1;
        msg!("Transfer: {} -> {} (sequence {})", prev_holder, new_holder, material_account.last_sequence);
        Ok(())
    }

    // (Additional instructions like quarantine or finalize could be added similarly)
}

/// Account data: stores info about the material.
#[account]  // Anchor will generate serialization logic for this account.
pub struct Material {
    pub current_holder: Pubkey,       // 32 bytes
    pub last_sequence: u64,           // 8 bytes (number of custody transfers that have occurred)
    pub id: [u8; Material::MAX_ID_LEN] // fixed-size array for material ID
    // You could add more fields like status, timestamps, etc., as needed.
}

impl Material {
    pub const MAX_ID_LEN: usize = 20;            // maximum length for material ID (20 bytes)
    pub const SIZE: usize = 8 + 32 + 8 + 20;     // account size (discriminator + fields)
}

/// Context for initializing a material.
#[derive(Accounts)]
pub struct InitializeMaterial<'info> {
    #[account(
        init, 
        payer = initializer, 
        space = Material::SIZE
        // In a real app, consider using seeds and bump for a PDA (see notes below)
    )]
    pub material_account: Account<'info, Material>,
    #[account(mut)]
    pub initializer: Signer<'info>,            // payer and initial holder
    pub system_program: Program<'info, System>
}

/// Context for transferring a material.
#[derive(Accounts)]
pub struct TransferMaterial<'info> {
    #[account(
        mut, 
        has_one = current_holder // ensures the signer is the current_holder
    )]
    pub material_account: Account<'info, Material>,
    pub current_holder: Signer<'info>          // must match material_account.current_holder
}