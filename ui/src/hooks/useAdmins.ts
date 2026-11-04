import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createAdmin,
  listAdmins,
  updateAdmin,
  type CreateAdminInput,
  type UpdateAdminInput,
} from '../api/client';
import { adminAuditPrefix, adminsPrefix, queryKeys } from '../lib/queryKeys';

export const ADMIN_PAGE_SIZE = 50;

export function useAdmins(offset: number) {
  return useQuery({
    queryKey: queryKeys.admins(ADMIN_PAGE_SIZE, offset),
    queryFn: ({ signal }) => listAdmins({ limit: ADMIN_PAGE_SIZE, offset }, signal),
    retry: false,
  });
}

export function useCreateAdmin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: CreateAdminInput) => createAdmin(input),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: adminsPrefix }),
        queryClient.invalidateQueries({ queryKey: adminAuditPrefix }),
      ]);
    },
  });
}

export function useUpdateAdmin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (args: { adminId: string; patch: UpdateAdminInput }) =>
      updateAdmin(args.adminId, args.patch),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: adminsPrefix }),
        queryClient.invalidateQueries({ queryKey: adminAuditPrefix }),
      ]);
    },
  });
}
