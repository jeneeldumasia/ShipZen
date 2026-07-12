import { auth } from "@/auth";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { Shield, ShieldAlert, User as UserIcon } from "lucide-react";
import { getBaseUrl } from "@/lib/api";

async function getUsers(token: string) {
  const res = await fetch(`${getBaseUrl()}/admin/users`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  });
  if (!res.ok) return [];
  return res.json();
}

export default async function AdminUsersPage() {
  const session = await auth();
  if (!(session as { accessToken?: string })?.accessToken) redirect("/login");

  const users = await getUsers((session as { accessToken?: string }).accessToken as string);

  async function promoteUser(formData: FormData) {
    "use server";
    const userId = formData.get("userId") as string;
    const role = formData.get("role") as string;
    
    // Server action to promote/demote
    await fetch(`${getBaseUrl()}/admin/users/${userId}/role`, {
      method: "PUT",
      headers: { 
        "Content-Type": "application/json",
        Authorization: `Bearer ${(session as { accessToken?: string })?.accessToken}` 
      },
      body: JSON.stringify({ role })
    });
    
    revalidatePath("/admin/users");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3 mb-8">
        <div className="p-3 bg-brand/20 rounded-xl shadow-glow">
          <Shield className="w-6 h-6 text-brand" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-text-primary tracking-tight">User Management</h1>
          <p className="text-text-secondary mt-1">Manage platform access and assign admin roles.</p>
        </div>
      </div>

      <div className="rounded-xl border border-canvas-border bg-canvas-bg/40 overflow-hidden backdrop-blur-xl shadow-2xl">
        <table className="w-full text-left text-sm text-text-secondary">
          <thead className="bg-canvas-border/50 text-xs uppercase font-semibold text-text-primary">
            <tr>
              <th className="px-6 py-4">User ID</th>
              <th className="px-6 py-4">Email</th>
              <th className="px-6 py-4">Joined</th>
              <th className="px-6 py-4">Role</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-canvas-border">
            {users.map((u: any) => (
              <tr key={u.id} className="hover:bg-canvas-border/50 transition-colors">
                <td className="px-6 py-4 font-mono text-xs">{u.id}</td>
                <td className="px-6 py-4">{u.email || "No Email"}</td>
                <td className="px-6 py-4">{new Date(u.created_at).toLocaleDateString()}</td>
                <td className="px-6 py-4">
                  <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                    u.role === "admin" ? "bg-red-500/20 text-red-600 dark:text-red-400" : "bg-canvas-border text-text-secondary"
                  }`}>
                    {u.role === "admin" ? <ShieldAlert size={12} /> : <UserIcon size={12} />}
                    {u.role}
                  </span>
                </td>
                <td className="px-6 py-4 text-right">
                  <form action={promoteUser}>
                    <input type="hidden" name="userId" value={u.id} />
                    <input type="hidden" name="role" value={u.role === "admin" ? "user" : "admin"} />
                    <button type="submit" className="text-xs px-3 py-1.5 rounded-lg bg-canvas-border hover:bg-canvas-border/80 text-text-primary transition-colors">
                      {u.role === "admin" ? "Demote to User" : "Promote to Admin"}
                    </button>
                  </form>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center">No users found.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
